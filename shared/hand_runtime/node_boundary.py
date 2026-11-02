"""Request-bound Core evidence, replay rejection and bounded MCP output."""

import asyncio
import base64
import hashlib
import logging
import time
import traceback
from collections.abc import Callable
from dataclasses import dataclass, field
from uuid import UUID

from mcp.types import CallToolRequest
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from node_protocol.effect import EffectPermit, EffectRejected, EffectVerifier
from node_protocol.json_boundary import decode_json

from .provider_ipc import ProviderContext as PrivateInvocationContext


def _record_rejection(error: Exception, stage: str) -> None:
    cause = error.__cause__ or error.__context__ or error
    if stage == "execution":
        logging.getLogger(__name__).warning(
            "Node pending task frames=%s",
            tuple(
                tuple((frame.f_code.co_name, frame.f_lineno) for frame in task.get_stack(limit=4))
                for task in asyncio.all_tasks()
                if not task.done()
            ),
        )
    logging.getLogger(__name__).warning(
        "Node request rejected stage=%s category=%s frames=%s",
        stage,
        type(cause).__name__,
        tuple((frame.name, frame.lineno) for frame in traceback.extract_tb(cause.__traceback__)),
    )


class _BodyTooLarge(ValueError):
    pass


@dataclass(frozen=True)
class _Invocation:
    body: bytes
    permit: EffectPermit
    context: PrivateInvocationContext | None
    call: CallToolRequest | None


@dataclass
class _CaptureReceive:
    receive: Receive
    message: Message | None = None

    async def __call__(self) -> Message:
        message = await self.receive()
        if self.message is None and message["type"] == "http.request":
            self.message = dict(message)
        return message


@dataclass
class _ResponseBuffer:
    messages: list[Message] = field(default_factory=list)
    size: int = 0

    async def send(self, message: Message) -> None:
        if message["type"] == "http.response.body":
            self.size += len(message.get("body", b""))
        if self.size > 1_048_576 or len(self.messages) >= 128:
            raise ValueError("Bounded executor response required")
        self.messages.append(message)


def _accepts(request: Request) -> bool:
    return (
        request.scope.get("raw_path") == b"/mcp"
        and request.method == "POST"
        and not request.scope.get("query_string")
        and request.headers.getlist("content-type") == ["application/json"]
        and not request.headers.getlist("cookie")
        and not request.headers.getlist("origin")
        and all(
            len(request.headers.getlist(name)) == 1
            for name in ("authorization", "x-briareus-node-permit")
        )
    )


def _invocation_context(request: Request, permit: EffectPermit) -> PrivateInvocationContext | None:
    contexts = request.headers.getlist("x-briareus-invocation-context")
    if not permit.context_digest:
        if contexts:
            raise ValueError("Unbound invocation context")
        return None
    if len(contexts) != 1 or len(contexts[0]) > 11000:
        raise ValueError("Private invocation context missing")
    raw = base64.b64decode(contexts[0], validate=True)
    if len(raw) > 8192 or hashlib.sha256(raw).hexdigest() != permit.context_digest:
        raise ValueError("Wrong invocation context")
    return decode_json(raw, PrivateInvocationContext)


class EffectBoundary:
    def __init__(
        self,
        app: ASGIApp,
        verifier: EffectVerifier,
        *,
        code: str = "FILES_CURRENT_AUTHORITY_REQUIRED",
        ready: Callable[[], bool] = lambda: True,
    ) -> None:
        self.app, self.verifier, self.code = app, verifier, code
        self.ready = ready
        self.nonces: dict[UUID, int] = {}
        self.slots = asyncio.Semaphore(32)

    def _health(self, request: Request) -> JSONResponse | None:
        if (
            request.scope["path"] not in {"/health/live", "/health/ready"}
            or request.method != "GET"
        ):
            return None
        if request.scope["path"] == "/health/ready" and not self.ready():
            return JSONResponse({"state": "starting"}, status_code=503)
        return JSONResponse({"state": "live", "authorization": "per_request_core_required"})

    async def _authorize(self, request: Request) -> _Invocation:
        body = bytearray()
        async with asyncio.timeout(3):
            async for chunk in request.stream():
                if len(body) + len(chunk) > 32768:
                    raise _BodyTooLarge("Bounded MCP request required")
                body.extend(chunk)
        raw = bytes(body)
        permit = self.verifier.verify(
            request.headers["x-briareus-node-permit"],
            body=raw,
            bearer=request.headers["authorization"],
        )
        call = CallToolRequest.model_validate_json(raw) if permit.method == "tools/call" else None
        return _Invocation(raw, permit, _invocation_context(request, permit), call)

    def _admission_status(self, permit: EffectPermit) -> int | None:
        self.nonces = {key: expiry for key, expiry in self.nonces.items() if expiry > time.time()}
        if permit.request_uuid in self.nonces:
            return 409
        if len(self.nonces) >= 4096:
            return 429
        return None

    async def _execute(
        self,
        invocation: _Invocation,
        scope: Scope,
        receive: Receive,
        send: Send,
        request_message: Message,
    ) -> None:
        permit = invocation.permit
        authorized_scope = dict(scope)
        authorized_scope["briareus.node_effect"] = permit
        authorized_scope["briareus.invocation_context"] = invocation.context
        authorized_scope["briareus.node_call"] = invocation.call
        # Reuse the received ASGI frame with the exact verified body, then resume
        # the original channel for subsequent disconnect/receive messages.
        request_message.clear()
        request_message.update(type="http.request", body=invocation.body, more_body=False)
        delivered = False

        async def replay() -> Message:
            nonlocal delivered
            if not delivered:
                delivered = True
                return request_message
            return await receive()

        buffer = _ResponseBuffer()
        async with asyncio.timeout(max(0, permit.expires_at - time.time())):
            await self.app(authorized_scope, replay, buffer.send)
        # Nothing leaves the executor after its authority expires.
        if permit.expires_at <= time.time():
            raise ValueError("Expired executor response")
        for message in buffer.messages:
            await send(message)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        capture = _CaptureReceive(receive)
        request = Request(scope, capture)

        async def reject(status: int = 403) -> None:
            await JSONResponse(
                {"code": self.code},
                status_code=status,
                headers={"cache-control": "no-store"},
            )(scope, receive, send)

        health = self._health(request)
        if health is not None:
            return await health(scope, receive, send)
        if not self.ready():
            return await reject(503)
        if not _accepts(request):
            return await reject()
        try:
            invocation = await self._authorize(request)
            request_message = capture.message
            if request_message is None:
                raise ValueError("Original HTTP request frame required")
        except _BodyTooLarge:
            return await reject(413)
        except (EffectRejected, TimeoutError, ValueError) as error:
            _record_rejection(error, "admission")
            return await reject()
        status = self._admission_status(invocation.permit)
        if status is not None:
            return await reject(status)
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=1)
        except TimeoutError:
            return await reject(429)
        try:
            permit = invocation.permit
            if permit.request_uuid in self.nonces or permit.expires_at <= time.time():
                return await reject(409)
            self.nonces[permit.request_uuid] = permit.expires_at
            await self._execute(invocation, scope, receive, send, request_message)
        except (TimeoutError, ValueError) as error:
            _record_rejection(error, "execution")
            return await reject()
        finally:
            self.slots.release()
