"""Actual HTTP/2 Protobuf RPC, independent signatures and durable event replay."""

import socket
import tempfile
import time
import unittest
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4

import grpc
from control_fixture import ControlRuntimeFixture, NoEffectsScheduler
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from journal_fixture import JournalFixture as Journal
from node_agent.application.control import NodeControl
from node_agent.control_auth import CoreVerifier
from node_agent.grpc_server import start_server
from node_agent.identity import NodeIdentity
from test_reconciliation import fixture

from node_protocol import NodeRecord
from node_protocol import node_pb2 as pb
from node_protocol.control import ControlCommand
from node_protocol.domain.observations import (
    NodeConfiguration,
    NodeFailure,
    NodeInventory,
    NodeOperation,
)
from node_protocol.grpc_codec import decode_reply, encode_command
from node_protocol.grpc_events import NodeEventVerifier
from node_protocol.replies import NodeReplyVerifier
from node_protocol.reply_wire import NodeReplyWire


class PendingScheduler(NoEffectsScheduler):
    def __init__(self) -> None:
        self.pending: set[UUID] = set()

    def active(self, operation: UUID) -> bool:
        return operation in self.pending


class RpcClient:
    def __init__(self, channel: grpc.aio.Channel) -> None:
        self.channel = channel
        self.Inventory = self.unary("Inventory")
        self.Configure = self.unary("Configure")
        self.Operation = self.unary("Operation")
        self.Watch: grpc.aio.UnaryStreamMultiCallable[pb.SignedCommand, pb.SignedEvent] = (
            channel.unary_stream(
                "/briareus.node.NodeControl/Watch",
                request_serializer=pb.SignedCommand.SerializeToString,
                response_deserializer=pb.SignedEvent.FromString,
            )
        )

    def unary(
        self, name: str
    ) -> grpc.aio.UnaryUnaryMultiCallable[pb.SignedCommand, pb.SignedReply]:
        return self.channel.unary_unary(
            "/briareus.node.NodeControl/" + name,
            request_serializer=pb.SignedCommand.SerializeToString,
            response_deserializer=pb.SignedReply.FromString,
        )


async def read_event(
    stream: grpc.aio.UnaryStreamCall[pb.SignedCommand, pb.SignedEvent],
) -> pb.SignedEvent:
    event = await stream.read()
    if not isinstance(event, pb.SignedEvent):
        raise AssertionError("Signed event expected before stream completion")
    return event


class GrpcControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_commands_authentication_live_events_and_replay(self) -> None:
        node, spec = fixture()
        key = Ed25519PrivateKey.generate()
        public = key.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "journal-fixture")
            identity = NodeIdentity(Path(folder) / "node.key")
            verifier = CoreVerifier(public, node.id)

            scheduler = PendingScheduler()
            service = NodeControl(node, ControlRuntimeFixture(node), journal, scheduler)

            async def control(command: ControlCommand, signature: str) -> tuple[int, NodeReplyWire]:
                with journal.authority(command, signature):
                    result = await service.execute(command)
                return result.status, identity.reply(command, result.status, result.payload)

            with socket.socket() as probe:
                probe.bind(("127.0.0.1", 0))
                port = probe.getsockname()[1]
            server = await start_server(
                f"127.0.0.1:{port}",
                verifier=verifier,
                identity=identity,
                handler=control,
                journal=journal,
                node_uuid=node.id,
            )
            channel = grpc.aio.insecure_channel(
                f"127.0.0.1:{port}"
            )  # Disposable loopback fixture only.
            stub = RpcClient(channel)
            streams: list[grpc.aio.UnaryStreamCall[pb.SignedCommand, pb.SignedEvent]] = []

            def command(
                action: Literal["inventory", "configure", "status", "watch"],
                *,
                operation_uuid: UUID | None = None,
                sequence: int = 1,
                node_record: NodeRecord | None = None,
                after_event: int = 0,
            ) -> ControlCommand:
                return ControlCommand(
                    node_uuid=node.id,
                    operation_uuid=uuid4() if operation_uuid is None else operation_uuid,
                    sequence=sequence,
                    action=action,
                    node_record=node_record,
                    after_event=after_event,
                    issued_at=int(time.time()),
                    expires_at=int(time.time()) + 30,
                )

            def signed(value: ControlCommand) -> pb.SignedCommand:
                return encode_command(value, key.sign(value.signing_bytes()))

            try:
                with self.assertRaises(grpc.aio.AioRpcError) as denied:
                    await stub.Inventory(pb.SignedCommand(), timeout=3)
                self.assertEqual(denied.exception.code(), grpc.StatusCode.PERMISSION_DENIED)
                inventory = command("inventory")
                with self.assertRaises(grpc.aio.AioRpcError):
                    await stub.Configure(signed(inventory), timeout=3)
                unknown = pb.SignedCommand.FromString(
                    signed(inventory).SerializeToString() + b"\x98\x06\x01"
                )
                with self.assertRaises(grpc.aio.AioRpcError):
                    await stub.Inventory(unknown, timeout=3)
                response = await stub.Inventory(signed(inventory), timeout=3)
                payload = NodeReplyVerifier(identity.public_key.encode()).verify(
                    inventory, 200, decode_reply(response)
                )
                assert isinstance(payload, NodeInventory)
                self.assertEqual(payload.event_cursor, 0)
                configure = command("configure", node_record=node, sequence=2)
                response = await stub.Configure(signed(configure), timeout=3)
                self.assertEqual(response.WhichOneof("result"), "configuration")
                configured = NodeReplyVerifier(identity.public_key.encode()).verify(
                    configure, 200, decode_reply(response)
                )
                assert isinstance(configured, NodeConfiguration)
                self.assertEqual(configured.sequence, 2)
                subscription = command("watch")
                stream = stub.Watch(signed(subscription), timeout=5)
                streams.append(stream)
                events = NodeEventVerifier(identity.public_key.encode(), subscription)
                first = events.verify(await read_event(stream))
                self.assertEqual(first.topic, "configuration")
                operation = uuid4()
                (await journal.reserve(operation, 1, spec))
                scheduler.pending.add(operation)
                status_command = command("status", operation_uuid=operation)
                response = await stub.Operation(signed(status_command), timeout=3)
                self.assertEqual(response.WhichOneof("result"), "operation")
                status = NodeReplyVerifier(identity.public_key.encode()).verify(
                    status_command, 200, decode_reply(response)
                )
                assert isinstance(status, NodeOperation)
                self.assertEqual(status.phase, "queued")
                self.assertIsNone(status.error)
                second = events.verify(await read_event(stream))
                assert isinstance(second.payload, NodeOperation)
                self.assertEqual(second.payload.operation_uuid, operation)
                (await journal.phase(operation, "pulling"))
                third = events.verify(await read_event(stream))
                assert isinstance(third.payload, NodeOperation)
                self.assertEqual(third.payload.phase, "pulling")
                resumed = command("watch", after_event=second.cursor)
                replay = stub.Watch(signed(resumed), timeout=5)
                streams.append(replay)
                event = await read_event(replay)
                self.assertEqual(
                    NodeEventVerifier(identity.public_key.encode(), resumed).verify(event).cursor,
                    third.cursor,
                )
                event.event.operation.phase = "succeeded"
                with self.assertRaises(ValueError):
                    NodeEventVerifier(identity.public_key.encode(), resumed).verify(event)
                (await journal.phase(operation, "failed", error="UPDATE_FAILED"))
                status_command = command("status", operation_uuid=operation)
                response = await stub.Operation(signed(status_command), timeout=3)
                status = NodeReplyVerifier(identity.public_key.encode()).verify(
                    status_command, 200, decode_reply(response)
                )
                assert isinstance(status, NodeOperation)
                self.assertEqual(status.error, "UPDATE_FAILED")
                self.assertEqual(status.phase, "failed")
                missing = command("status")
                response = await stub.Operation(signed(missing), timeout=3)
                self.assertEqual(response.WhichOneof("result"), "failure")
                failure = NodeReplyVerifier(identity.public_key.encode()).verify(
                    missing, 404, decode_reply(response)
                )
                assert isinstance(failure, NodeFailure)
                self.assertEqual(failure.code, "NODE_OPERATION_NOT_FOUND")
            finally:
                for stream in streams:
                    stream.cancel()
                await channel.close()
                await server.stop(1)
                (await journal.close())
