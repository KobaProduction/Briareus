"""Private typed gRPC control and durable event streaming. No REST control route."""

from __future__ import annotations

import asyncio
import base64
import logging
import time
import traceback
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Never, Protocol, cast
from uuid import UUID

import grpc
from grpc_health.v1 import health_pb2, health_pb2_grpc

from node_protocol import node_pb2 as pb
from node_protocol.control import ControlCommand
from node_protocol.grpc_codec import decode_command, encode_reply

from .application.events import EventHistory, ObserveNodeEvents
from .control_auth import ControlRejected, CoreVerifier
from .identity import NodeIdentity
from .journal import JournalUnavailable, OperationConflict
from .presentation.control_wire import SignedControlReply
from .presentation.grpc_health import create_async_health
from .presentation.node_events import signed_event

ControlHandler = Callable[[ControlCommand, str], Awaitable[tuple[int, SignedControlReply]]]


class EventJournal(EventHistory, Protocol):
    @property
    def listeners(self) -> set[asyncio.Event]: ...


type ControlMethod = (
    grpc.RpcMethodHandler[pb.SignedCommand, pb.SignedReply]
    | grpc.RpcMethodHandler[pb.SignedCommand, pb.SignedEvent]
)


class RegisteredMethods(Protocol):
    def add_registered_method_handlers(
        self, service_name: str, method_handlers: dict[str, ControlMethod]
    ) -> None: ...


class RpcContext(Protocol):
    async def abort(self, code: grpc.StatusCode, details: str) -> Never: ...

    def invocation_metadata(self) -> tuple[tuple[str, str | bytes], ...]: ...


class ControlService:
    def __init__(
        self,
        *,
        verifier: CoreVerifier,
        identity: NodeIdentity | None,
        handler: ControlHandler,
        journal: EventJournal,
        node_uuid: UUID,
    ) -> None:
        self.verifier, self.identity, self.handler, self.journal, self.node_uuid = (
            verifier,
            identity,
            handler,
            journal,
            node_uuid,
        )

    async def authenticate(
        self, request: pb.SignedCommand, context: RpcContext, action: str
    ) -> ControlCommand:
        if self.identity is None:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Node identity unavailable")
        if any(
            key.lower() in {"cookie", "origin", "authorization"}
            for key, _ in context.invocation_metadata()
        ):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Core service command required")
        try:
            command = decode_command(request)
            if command.action != action:
                raise ControlRejected("RPC method mismatch")
            self.verifier.verify(
                command.model_dump_json().encode(), base64.b64encode(request.signature).decode()
            )
            return command
        except (ValueError, TypeError):
            await context.abort(grpc.StatusCode.PERMISSION_DENIED, "Core service command rejected")

    async def execute(
        self, request: pb.SignedCommand, context: RpcContext, action: str
    ) -> pb.SignedReply:
        command = await self.authenticate(request, context, action)
        try:
            async with asyncio.timeout(min(6, command.expires_at - time.time())):
                _status, envelope = await self.handler(
                    command, base64.b64encode(request.signature).decode()
                )
            if command.expires_at <= time.time():
                await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Core authority expired")
            return encode_reply(command, envelope)
        except TimeoutError:
            await context.abort(grpc.StatusCode.DEADLINE_EXCEEDED, "Node command timed out")
        except grpc.RpcError:
            raise
        except Exception as error:
            frames = tuple(
                (frame.name, frame.lineno) for frame in traceback.extract_tb(error.__traceback__)
            )
            logging.getLogger(__name__).error(
                "Node control failed action=%s exception=%s frames=%s",
                action,
                type(error).__name__,
                frames,
            )
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Node command unavailable")

    async def Inventory(self, request: pb.SignedCommand, context: RpcContext) -> pb.SignedReply:
        return await self.execute(request, context, "inventory")

    async def Configure(self, request: pb.SignedCommand, context: RpcContext) -> pb.SignedReply:
        return await self.execute(request, context, "configure")

    async def Apply(self, request: pb.SignedCommand, context: RpcContext) -> pb.SignedReply:
        return await self.execute(request, context, "apply")

    async def Operation(self, request: pb.SignedCommand, context: RpcContext) -> pb.SignedReply:
        return await self.execute(request, context, "status")

    async def ObserveBrowser(
        self, request: pb.SignedCommand, context: RpcContext
    ) -> pb.SignedReply:
        return await self.execute(request, context, "observe_browser")

    async def Watch(
        self, request: pb.SignedCommand, context: RpcContext
    ) -> AsyncIterator[pb.SignedEvent]:
        command = await self.authenticate(request, context, "watch")
        changed = asyncio.Event()
        self.journal.listeners.add(changed)
        try:
            identity = self.identity
            if identity is None:
                await context.abort(grpc.StatusCode.UNAVAILABLE, "Node identity unavailable")
            stream = ObserveNodeEvents(self.journal, changed)
            async for row in stream.read(command.after_event, command.expires_at):
                yield signed_event(row, command, identity, self.node_uuid, int(time.time()))
        except OperationConflict:
            await context.abort(
                grpc.StatusCode.OUT_OF_RANGE, "Event cursor lost; obtain inventory and resume"
            )
        except JournalUnavailable:
            await context.abort(grpc.StatusCode.UNAVAILABLE, "Node journal unavailable")
        finally:
            self.journal.listeners.discard(changed)


def _serialize_reply(value: pb.SignedReply) -> bytes:
    return value.SerializeToString()


def _serialize_event(value: pb.SignedEvent) -> bytes:
    return value.SerializeToString()

def register_control(server: grpc.aio.Server, service: ControlService) -> None:
    # Same public binding as the generated adapter, with typed async callbacks.
    methods: dict[str, ControlMethod] = {
        name: grpc.unary_unary_rpc_method_handler(
            method,
            request_deserializer=pb.SignedCommand.FromString,
            response_serializer=_serialize_reply,
        )
        for name, method in (
            ("Inventory", service.Inventory),
            ("Configure", service.Configure),
            ("Apply", service.Apply),
            ("Operation", service.Operation),
            ("ObserveBrowser", service.ObserveBrowser),
        )
    }
    methods["Watch"] = grpc.unary_stream_rpc_method_handler(
        service.Watch,
        request_deserializer=pb.SignedCommand.FromString,
        response_serializer=_serialize_event,
    )
    name = "briareus.node.NodeControl"
    server.add_generic_rpc_handlers((grpc.method_handlers_generic_handler(name, methods),))
    cast(RegisteredMethods, server).add_registered_method_handlers(name, methods)


async def start_server(
    address: str,
    *,
    verifier: CoreVerifier,
    identity: NodeIdentity | None,
    handler: ControlHandler,
    journal: EventJournal,
    node_uuid: UUID,
) -> grpc.aio.Server:
    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", 65536),
            ("grpc.max_send_message_length", 1048576),
            ("grpc.so_reuseport", 0),
        ],
        maximum_concurrent_rpcs=32,
    )
    register_control(
        server,
        ControlService(
            verifier=verifier,
            identity=identity,
            handler=handler,
            journal=journal,
            node_uuid=node_uuid,
        ),
    )
    probe = create_async_health()
    health_pb2_grpc.add_HealthServicer_to_server(probe, server)
    await probe.set("", health_pb2.HealthCheckResponse.SERVING)
    if not server.add_insecure_port(address):
        raise ValueError("Private gRPC listener unavailable")
    await server.start()
    return server
