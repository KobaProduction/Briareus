"""Private typed gRPC control and durable event streaming. No REST control route."""
import asyncio
import base64
import hashlib
import json
import time
from datetime import datetime

import grpc
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

from node_protocol import node_pb2 as pb, node_pb2_grpc as rpc
from node_protocol.grpc_codec import decode_command, encode_reply, encode_operation
from .control_auth import ControlRejected
from node_protocol.grpc_events import EVENT_DOMAIN
from .journal import OperationConflict

class ControlService(rpc.NodeControlServicer):
    def __init__(self, *, verifier, identity, handler, journal, node_uuid):
        self.verifier,self.identity,self.handler,self.journal,self.node_uuid=verifier,identity,handler,journal,node_uuid

    async def authenticate(self, request, context, action):
        if self.identity is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE,"Node identity unavailable")
        if any(key.lower() in {"cookie","origin","authorization"} for key,_ in context.invocation_metadata()):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED,"Core service command required")
        try:
            command=decode_command(request)
            if command.action!=action:
                raise ControlRejected("RPC method mismatch")
            self.verifier.verify(command.model_dump_json().encode(),base64.b64encode(request.signature).decode())
            return command
        except (ValueError,TypeError):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED,"Core service command rejected")

    async def execute(self, request, context, action):
        command=await self.authenticate(request,context,action)
        try:
            async with asyncio.timeout(min(6,command.expires_at-time.time())):
                status,envelope=await self.handler(command)
            if command.expires_at<=time.time():
                await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED,"Core authority expired")
            return encode_reply(command,envelope)
        except TimeoutError:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED,"Node command timed out")
        except grpc.RpcError:
            raise
        except Exception:
            await context.abort(grpc.StatusCode.UNAVAILABLE,"Node command unavailable")

    async def Inventory(self, request, context):
        return await self.execute(request,context,"inventory")

    async def Configure(self, request, context):
        return await self.execute(request,context,"configure")

    async def Apply(self, request, context):
        return await self.execute(request,context,"apply")

    async def Operation(self, request, context):
        return await self.execute(request,context,"status")

    async def Watch(self, request, context):
        command=await self.authenticate(request,context,"watch")
        changed=asyncio.Event()
        self.journal.listeners.add(changed)
        cursor=command.after_event
        try:
            while command.expires_at>time.time():
                changed.clear()
                try:
                    rows=self.journal.events_after(cursor)
                except OperationConflict:
                    await context.abort(grpc.StatusCode.OUT_OF_RANGE,"Event cursor lost; obtain inventory and resume")
                if not rows:
                    try:
                        await asyncio.wait_for(changed.wait(),timeout=max(0,command.expires_at-time.time()))
                    except TimeoutError:
                        break
                for row in rows:
                    now=int(time.time())
                    if command.expires_at<=now:
                        return
                    event=pb.Event(node_uuid=str(self.node_uuid),cursor=row["cursor"])
                    event.created_at.FromDatetime(datetime.fromisoformat(row["created_at"]))
                    payload=json.loads(row["payload"])
                    if row["topic"]=="operation":
                        event.topic=pb.MODULE_OPERATION
                        event.operation.CopyFrom(encode_operation(payload))
                    else:
                        event.topic=pb.NODE_CONFIGURATION
                        event.configuration.CopyFrom(pb.Configuration(**payload))
                    envelope=pb.SignedEvent(event=event,subscription_uuid=str(command.operation_uuid),
                        issued_at=now,expires_at=min(now+15,command.expires_at),
                        request_digest=hashlib.sha256(command.signing_bytes()).digest())
                    envelope.signature=self.identity.key.sign(EVENT_DOMAIN+envelope.SerializeToString(deterministic=True))
                    yield envelope
                    cursor=row["cursor"]
        finally:
            self.journal.listeners.discard(changed)


async def start_server(address, **dependencies):
    server=grpc.aio.server(options=[("grpc.max_receive_message_length",65536),
        ("grpc.max_send_message_length",1048576), ("grpc.so_reuseport",0)],maximum_concurrent_rpcs=32)
    rpc.add_NodeControlServicer_to_server(ControlService(**dependencies),server)
    probe=health.aio.HealthServicer()
    health_pb2_grpc.add_HealthServicer_to_server(probe,server)
    await probe.set("",health_pb2.HealthCheckResponse.SERVING)
    if not server.add_insecure_port(address):
        raise ValueError("Private gRPC listener unavailable")
    await server.start()
    return server
