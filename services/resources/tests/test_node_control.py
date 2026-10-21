"""Actual TLS HTTP/2 RPC with ephemeral certificates and independent Ed25519 pins."""
import base64
import hashlib
import time
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

import grpc
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import node_pb2_grpc as rpc
from node_protocol.control import ReplyProof, canonical
from node_protocol.grpc_codec import decode_command, encode_reply
from projects.node_control import NodeControl, NodeUnavailable


class NodeControlTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.core_key,self.node_key=Ed25519PrivateKey.generate(),Ed25519PrivateKey.generate()
        self.node_public=self.node_key.public_key().public_bytes(serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo).decode()
        self.core=NodeControl(self.core_key,frozenset({"https://node.example"}))
        self.calls=[]
        self.mode="normal"
        owner=self
        class Service(rpc.NodeControlServicer):
            async def Inventory(self, request, context):
                command=decode_command(request)
                owner.core_key.public_key().verify(request.signature,command.signing_bytes())
                owner.calls.append(command.node_uuid)
                if owner.mode=="unavailable":
                    await context.abort(grpc.StatusCode.UNAVAILABLE,"fixture upstream error must stay private")
                payload={"node_uuid":str(command.node_uuid),"enabled":False,"sequence":0,"items":[],"event_cursor":0}
                if owner.mode=="oversized":
                    payload={"error":{"code":"x"*1048577}}
                now=int(time.time())
                proof=ReplyProof(node_uuid=command.node_uuid,operation_uuid=command.operation_uuid,
                    request_digest=hashlib.sha256(command.signing_bytes()).hexdigest(),
                    response_digest=hashlib.sha256(canonical(payload)).hexdigest(),status_code=200,
                    issued_at=now,expires_at=now+15)
                key=Ed25519PrivateKey.generate() if owner.mode=="wrongpin" else owner.node_key
                return encode_reply(command,{"result":payload,"proof":proof.model_dump(mode="json"),
                    "signature":base64.b64encode(key.sign(proof.signing_bytes())).decode()})
        tls_key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        name=x509.Name([x509.NameAttribute(x509.oid.NameOID.COMMON_NAME,"node.example")])
        cert=x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(tls_key.public_key()).serial_number(
            x509.random_serial_number()).not_valid_before(datetime.now(UTC)-timedelta(minutes=1)).not_valid_after(
            datetime.now(UTC)+timedelta(hours=1)).add_extension(x509.SubjectAlternativeName([x509.DNSName("node.example")]),False).sign(tls_key,hashes.SHA256())
        pem=cert.public_bytes(serialization.Encoding.PEM)
        self.server=grpc.aio.server()
        rpc.add_NodeControlServicer_to_server(Service(),self.server)
        port=self.server.add_secure_port("127.0.0.1:0",grpc.ssl_server_credentials([(tls_key.private_bytes(
            serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()),pem)]))
        await self.server.start()
        self.channel=grpc.aio.secure_channel(f"127.0.0.1:{port}",grpc.ssl_channel_credentials(pem),options=[
            ("grpc.ssl_target_name_override","node.example"),("grpc.max_receive_message_length",1048576),
            ("grpc.enable_retries",0)])

    async def asyncTearDown(self):
        await self.channel.close()
        await self.server.stop(1)

    async def call(self, endpoint="https://node.example"):
        with patch.object(self.core,"channel",return_value=self.channel):
            return await self.core.call(endpoint=endpoint,public_key=self.node_public,
                node_uuid=uuid4(),operation_uuid=uuid4(),sequence=1)

    async def test_real_tls_protobuf_signature_exchange(self):
        result=await self.call()
        self.assertFalse(result["enabled"])
        self.assertEqual(len(self.calls),1)

    async def test_wrong_pin_oversized_and_transport_failure_are_closed(self):
        for self.mode in ("wrongpin","oversized","unavailable"):
            with self.assertRaises(NodeUnavailable) as denied:
                await self.call()
            self.assertEqual(str(denied.exception),"Authenticated node control unavailable")

    async def test_unapproved_origin_is_never_contacted(self):
        with self.assertRaises(NodeUnavailable):
            await self.call("https://node.example.evil")
        self.assertEqual(self.calls,[])
