"""Actual TLS HTTP/2 RPC with ephemeral certificates and independent Ed25519 pins."""

import base64
import hashlib
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

import grpc
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects.node_control import NodeControl, NodeUnavailable

from node_protocol import node_pb2 as pb
from node_protocol import node_pb2_grpc as rpc
from node_protocol.control import ReplyProof, canonical
from node_protocol.domain.observations import NodeInventory, NodeReply
from node_protocol.grpc_codec import decode_command, encode_reply
from node_protocol.reply_wire import InventoryWire, NodeReplyWire


class NodeControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.core_key, self.node_key = Ed25519PrivateKey.generate(), Ed25519PrivateKey.generate()
        self.node_public = (
            self.node_key.public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode()
        )
        self.core = NodeControl(self.core_key, frozenset({"https://node.example"}))
        self.calls: list[UUID] = []
        self.mode = "normal"
        owner = self

        class Service(rpc.NodeControlServicer):
            async def Inventory(
                self,
                request: pb.SignedCommand,
                context: grpc.aio.ServicerContext[pb.SignedCommand, pb.SignedReply],
            ) -> pb.SignedReply:
                command = decode_command(request)
                owner.core_key.public_key().verify(request.signature, command.signing_bytes())
                owner.calls.append(command.node_uuid)
                if owner.mode == "unavailable":
                    await context.abort(
                        grpc.StatusCode.UNAVAILABLE, "fixture upstream error must stay private"
                    )
                payload = InventoryWire(
                    node_uuid=command.node_uuid, enabled=False, sequence=0, items=(), event_cursor=0
                )
                now = int(time.time())
                proof = ReplyProof(
                    node_uuid=command.node_uuid,
                    operation_uuid=command.operation_uuid,
                    request_digest=hashlib.sha256(command.signing_bytes()).hexdigest(),
                    response_digest=hashlib.sha256(
                        canonical(payload.model_dump(mode="json"))
                    ).hexdigest(),
                    status_code=200,
                    issued_at=now,
                    expires_at=now + 15,
                )
                key = Ed25519PrivateKey.generate() if owner.mode == "wrongpin" else owner.node_key
                reply = encode_reply(
                    command,
                    NodeReplyWire(
                        result=payload,
                        proof=proof,
                        signature=base64.b64encode(key.sign(proof.signing_bytes())).decode(),
                    ),
                )
                if owner.mode == "oversized":
                    reply.signature = b"x" * 1048577
                return reply

        tls_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        name = x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME, "node.example")])
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(tls_key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.now(UTC) - timedelta(minutes=1))
            .not_valid_after(datetime.now(UTC) + timedelta(hours=1))
            .add_extension(x509.SubjectAlternativeName([x509.DNSName("node.example")]), False)
            .sign(tls_key, hashes.SHA256())
        )
        pem = cert.public_bytes(serialization.Encoding.PEM)
        self.server = grpc.aio.server()
        self.server.add_generic_rpc_handlers(
            (
                grpc.method_handlers_generic_handler(
                    "briareus.node.NodeControl",
                    {
                        "Inventory": grpc.unary_unary_rpc_method_handler(
                            Service().Inventory,
                            request_deserializer=pb.SignedCommand.FromString,
                            response_serializer=pb.SignedReply.SerializeToString,
                        )
                    },
                ),
            )
        )
        port = self.server.add_secure_port(
            "127.0.0.1:0",
            grpc.ssl_server_credentials(
                [
                    (
                        tls_key.private_bytes(
                            serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8,
                            serialization.NoEncryption(),
                        ),
                        pem,
                    )
                ]
            ),
        )
        await self.server.start()
        self.channel = grpc.aio.secure_channel(
            f"127.0.0.1:{port}",
            grpc.ssl_channel_credentials(pem),
            options=[
                ("grpc.ssl_target_name_override", "node.example"),
                ("grpc.max_receive_message_length", 1048576),
                ("grpc.enable_retries", 0),
            ],
        )

    async def asyncTearDown(self) -> None:
        await self.channel.close()
        await self.server.stop(1)

    async def call(self, endpoint: str = "https://node.example") -> NodeReply:
        with patch.object(self.core, "channel", return_value=self.channel):
            return await self.core.call(
                endpoint=endpoint,
                public_key=self.node_public,
                node_uuid=uuid4(),
                operation_uuid=uuid4(),
                sequence=1,
            )

    async def test_real_tls_protobuf_signature_exchange(self) -> None:
        result = await self.call()
        assert isinstance(result, NodeInventory)
        self.assertFalse(result.enabled)
        self.assertEqual(len(self.calls), 1)

    async def test_wrong_pin_oversized_and_transport_failure_are_closed(self) -> None:
        for self.mode in ("wrongpin", "oversized", "unavailable"):
            with self.assertRaises(NodeUnavailable) as denied:
                await self.call()
            self.assertEqual(str(denied.exception), "Authenticated node control unavailable")

    async def test_unapproved_origin_is_never_contacted(self) -> None:
        with self.assertRaises(NodeUnavailable):
            await self.call("https://node.example.evil")
        self.assertEqual(self.calls, [])
