"""Actual HTTP/2 Protobuf RPC, independent signatures and durable event replay."""
import socket
import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

import grpc
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from node_protocol import node_pb2 as pb, node_pb2_grpc as rpc
from node_protocol.control import ControlCommand
from node_protocol.grpc_codec import encode_command, decode_reply
from node_protocol.grpc_events import NodeEventVerifier
from node_protocol.replies import NodeReplyVerifier
from node_agent.control_auth import CoreVerifier
from node_agent.identity import NodeIdentity
from node_agent.journal import Journal
from node_agent.grpc_server import start_server
from node_agent.server import create_app
from test_reconciliation import FakeEngine, fixture


class GrpcControlTests(unittest.IsolatedAsyncioTestCase):
    async def test_typed_commands_authentication_live_events_and_replay(self):
        node,spec=fixture()
        key=Ed25519PrivateKey.generate()
        public=key.public_key().public_bytes(serialization.Encoding.PEM,serialization.PublicFormat.SubjectPublicKeyInfo)
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/"journal.sqlite")
            identity=NodeIdentity(Path(folder)/"node.key")
            verifier=CoreVerifier(public,node.id)
            class Engine(FakeEngine):
                async def containers(self,node_uuid):
                    return []
            app=create_app(node,Engine(),journal,verifier,identity)
            with socket.socket() as probe:
                probe.bind(("127.0.0.1",0))
                port=probe.getsockname()[1]
            server=await start_server(f"127.0.0.1:{port}",verifier=verifier,identity=identity,
                handler=app.state.node_control,journal=journal,node_uuid=node.id)
            channel=grpc.aio.insecure_channel(f"127.0.0.1:{port}")  # Disposable loopback fixture only.
            stub=rpc.NodeControlStub(channel)
            streams=[]
            def command(action,**updates):
                values=dict(node_uuid=node.id,operation_uuid=uuid4(),sequence=1,action=action,
                    issued_at=int(time.time()),expires_at=int(time.time())+30)
                values.update(updates)
                return ControlCommand(**values)
            def signed(value):
                return encode_command(value,key.sign(value.signing_bytes()))
            try:
                with self.assertRaises(grpc.aio.AioRpcError) as denied:
                    await stub.Inventory(pb.SignedCommand(),timeout=3)
                self.assertEqual(denied.exception.code(),grpc.StatusCode.PERMISSION_DENIED)
                inventory=command("inventory")
                with self.assertRaises(grpc.aio.AioRpcError):
                    await stub.Configure(signed(inventory),timeout=3)
                unknown=pb.SignedCommand.FromString(signed(inventory).SerializeToString()+b'\x98\x06\x01')
                with self.assertRaises(grpc.aio.AioRpcError):
                    await stub.Inventory(unknown,timeout=3)
                response=await stub.Inventory(signed(inventory),timeout=3)
                payload=NodeReplyVerifier(identity.public_key.encode()).verify(inventory,200,decode_reply(response))
                self.assertEqual(payload["event_cursor"],0)
                configure=command("configure",node_record=node,sequence=2)
                response=await stub.Configure(signed(configure),timeout=3)
                self.assertEqual(response.WhichOneof("result"),"configuration")
                self.assertEqual(NodeReplyVerifier(identity.public_key.encode()).verify(configure,200,
                    decode_reply(response))["sequence"],2)
                subscription=command("watch")
                stream=stub.Watch(signed(subscription),timeout=5)
                streams.append(stream)
                events=NodeEventVerifier(identity.public_key.encode(),subscription)
                first=events.verify(await stream.read())
                self.assertEqual(first["topic"],"configuration")
                operation=uuid4()
                journal.reserve(operation,1,spec)
                status_command=command("status",operation_uuid=operation)
                response=await stub.Operation(signed(status_command),timeout=3)
                self.assertEqual(response.WhichOneof("result"),"operation")
                status=NodeReplyVerifier(identity.public_key.encode()).verify(status_command,200,decode_reply(response))
                self.assertEqual(status["phase"],"queued")
                self.assertIsNone(status["error"])
                second=events.verify(await stream.read())
                self.assertEqual(second["payload"]["operation_uuid"],str(operation))
                journal.phase(operation,"pulling")
                third=events.verify(await stream.read())
                self.assertEqual(third["payload"]["phase"],"pulling")
                resumed=command("watch",after_event=second["cursor"])
                replay=stub.Watch(signed(resumed),timeout=5)
                streams.append(replay)
                event=await replay.read()
                self.assertEqual(NodeEventVerifier(identity.public_key.encode(),resumed).verify(event)["cursor"],third["cursor"])
                event.event.operation.phase="succeeded"
                with self.assertRaises(ValueError):
                    NodeEventVerifier(identity.public_key.encode(),resumed).verify(event)
                journal.phase(operation,"failed",error="UPDATE_FAILED")
                status_command=command("status",operation_uuid=operation)
                response=await stub.Operation(signed(status_command),timeout=3)
                status=NodeReplyVerifier(identity.public_key.encode()).verify(status_command,200,decode_reply(response))
                self.assertEqual(status["error"],"UPDATE_FAILED")
                self.assertEqual(status["phase"],"failed")
                missing=command("status")
                response=await stub.Operation(signed(missing),timeout=3)
                self.assertEqual(response.WhichOneof("result"),"failure")
                self.assertEqual(NodeReplyVerifier(identity.public_key.encode()).verify(missing,404,
                    decode_reply(response))["error"]["code"],"NODE_OPERATION_NOT_FOUND")
            finally:
                for stream in streams:
                    stream.cancel()
                await channel.close()
                await server.stop(1)
                journal.close()
