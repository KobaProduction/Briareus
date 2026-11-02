"""Bounded signed MCP transport shared by controller ingress and private Gateway."""

import asyncio
import base64
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from uuid import UUID

import httpx
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from gateway_runtime.start import PendingProxyStart
from gateway_runtime.stream import ProxyStreamingResponse
from node_protocol.effect import HumanEffectPermit, NodeEffectPermit, SignedEffectPermit
from node_protocol.forward import (
    ForwardProof,
    ForwardRejected,
    ForwardVerifier,
    HumanForwardProof,
    TransportProof,
)
from node_protocol.json_boundary import decode_json
from node_protocol.provider_context import InvocationContext

from .runtime_profiles import SUPERVISOR_MODULES

Admission = Callable[[TransportProof, str], str | Awaitable[str]]
REQUIRED = ("authorization", "x-briareus-node-proof", "x-briareus-node-signature")
LOG = logging.getLogger(__name__)


class RelayBodyTooLarge(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class RelayCall:
    proof: TransportProof
    body: bytes
    bearer: str
    encoded_proof: str
    gateway_signature: str
    effect: str
    context: str


def unavailable(code: str = "NODE_MCP_UNAVAILABLE", status: int = 503) -> JSONResponse:
    return JSONResponse(
        {"code": code},
        status_code=status,
        headers={"cache-control": "no-store", "x-content-type-options": "nosniff"},
    )


def framing_accepted(request: Request) -> bool:
    return not (
        request.scope.get("raw_path") != b"/internal/v1/node/mcp"
        or request.url.query
        or any(len(request.headers.getlist(name)) != 1 for name in REQUIRED)
        or len(request.headers.getlist("x-briareus-node-permit")) > 1
        or len(request.headers.getlist("x-briareus-invocation-context")) > 1
        or request.headers.getlist("cookie")
        or request.headers.getlist("origin")
        or request.headers.getlist("content-type") != ["application/json"]
    )


async def relay_body(request: Request) -> bytes:
    async with asyncio.timeout(3):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 1_048_576:
                raise RelayBodyTooLarge("Bounded relay body required")
    return bytes(body)


def private_context(request: Request) -> str:
    context = request.headers.get("x-briareus-invocation-context", "")
    if request.headers.getlist("x-briareus-invocation-context") and not context:
        raise ForwardRejected("An empty private invocation header is not allowed")
    if len(context) > 11000:
        raise ForwardRejected("Private invocation context exceeds transport bound")
    if context:
        raw = base64.b64decode(context, validate=True)
        if not 0 < len(raw) <= 8192:
            raise ForwardRejected("Bounded private invocation object required")
        decode_json(raw, InvocationContext)
    return context


def require_effect(proof: TransportProof, effect: str, context: str) -> None:
    if not proof.effect_digest:
        if isinstance(proof, HumanForwardProof):
            raise ForwardRejected("Human forwarding requires signed effect authority")
        if context:
            raise ForwardRejected("Private invocation requires bound effect authority")
        return
    envelope = decode_json(base64.b64decode(effect, validate=True), SignedEffectPermit)
    permit = envelope.permit
    if isinstance(proof, HumanForwardProof):
        if not isinstance(permit, HumanEffectPermit):
            raise ForwardRejected("Human forwarding requires human effect authority")
    elif not isinstance(permit, NodeEffectPermit) or (
        permit.agent_session_uuid != proof.agent_session_uuid
        or permit.grant_revision != proof.grant_revision
    ):
        raise ForwardRejected("Agent forwarding differs from effect authority")
    if permit.context_digest != proof.context_digest or any(
        getattr(permit, name) != getattr(proof, name)
        for name in (
            "node_uuid",
            "placement_uuid",
            "project_uuid",
            "request_uuid",
            "module",
            "fingerprint",
            "body_digest",
            "bearer_digest",
        )
    ):
        raise ForwardRejected("Private invocation differs from effect authority")


def verified_call(verifier: ForwardVerifier, request: Request, body: bytes) -> RelayCall:
    context = private_context(request)
    bearer, encoded, signature = (request.headers[name] for name in REQUIRED)
    effect = request.headers.get("x-briareus-node-permit", "")
    proof = verifier.verify(
        encoded, signature, body=body, bearer=bearer, effect=effect, context=context
    )
    require_effect(proof, effect, context)
    return RelayCall(proof, body, bearer, encoded, signature, effect, context)


def forwarding_headers(call: RelayCall, *, upstream_socket: bool) -> httpx.Headers:
    proof = call.proof
    if upstream_socket:
        headers = httpx.Headers(
            dict(
                zip(
                    REQUIRED, (call.bearer, call.encoded_proof, call.gateway_signature), strict=True
                )
            )
        )
    else:
        headers = httpx.Headers(
            {
                "authorization": call.bearer,
                "x-briareus-project-uuid": str(proof.project_uuid),
            }
        )
        if isinstance(proof, ForwardProof):
            headers["x-briareus-agent-session-uuid"] = str(proof.agent_session_uuid)
            headers["x-briareus-grant-revision"] = str(proof.grant_revision)
        if proof.protocol_version:
            headers["mcp-protocol-version"] = proof.protocol_version
        if proof.mcp_session_id:
            headers["mcp-session-id"] = proof.mcp_session_id
    headers.update(
        {"content-type": "application/json", "accept": "application/json, text/event-stream"}
    )
    if proof.effect_digest:
        headers["x-briareus-node-permit"] = call.effect
    if call.context:
        headers["x-briareus-invocation-context"] = call.context
    return headers


class McpRelay:
    def __init__(
        self,
        *,
        verifier: ForwardVerifier,
        client: httpx.AsyncClient,
        admit: Admission,
        upstream_socket: bool = False,
    ) -> None:
        self.verifier, self.client, self.admit = verifier, client, admit
        self.upstream_socket = upstream_socket
        self.slots = asyncio.Semaphore(32)
        self.responses: set[httpx.Response] = set()
        self.streams: set[ProxyStreamingResponse] = set()
        self.pending: set[PendingProxyStart] = set()
        self.nonces: dict[UUID, float] = {}
        self.closed = False

    async def close(self) -> None:
        self.closed = True
        await asyncio.gather(
            *(start.abort() for start in list(self.pending)), return_exceptions=True
        )
        await asyncio.gather(
            *(stream.aclose() for stream in list(self.streams)), return_exceptions=True
        )
        await self.client.aclose()

    async def send(self, call: RelayCall) -> httpx.Response:
        target = self.admit(call.proof, call.gateway_signature)
        if not isinstance(target, str):
            async with asyncio.timeout(3):
                target = await target
        headers = forwarding_headers(call, upstream_socket=self.upstream_socket)
        request = self.client.build_request("POST", target, content=call.body, headers=headers)
        start = PendingProxyStart(self.client, request)
        self.pending.add(start)
        try:
            return await start.take_response()
        finally:
            self.pending.discard(start)

    async def response(self, upstream: httpx.Response) -> Response:
        self.responses.add(upstream)
        stream = ProxyStreamingResponse(
            upstream, slots=self.slots, open_responses=self.responses, tracked_streams=self.streams
        )
        self.streams.add(stream)
        if self.closed or upstream.status_code not in {
            200,
            202,
            204,
            400,
            401,
            403,
            404,
            409,
            422,
            429,
            503,
        }:
            await stream.aclose()
            return unavailable()
        stream.raw_headers = [
            (key, value)
            for key, value in upstream.headers.raw
            if key.lower() in {b"content-type", b"mcp-session-id", b"mcp-protocol-version"}
        ]
        stream.raw_headers += [
            (b"cache-control", b"no-store"),
            (b"x-content-type-options", b"nosniff"),
        ]
        return stream

    async def forward(self, request: Request) -> Response:
        if self.closed:
            return unavailable()
        if not framing_accepted(request):
            return unavailable("NODE_GATEWAY_PROOF_REQUIRED", 403)
        try:
            call = verified_call(self.verifier, request, await relay_body(request))
        except RelayBodyTooLarge:
            return unavailable("NODE_MCP_BODY_TOO_LARGE", 413)
        except (ForwardRejected, TimeoutError, ValueError, KeyError, TypeError):
            LOG.warning(
                "Node forwarding proof rejected controller_ingress=%s", self.upstream_socket
            )
            return unavailable("NODE_GATEWAY_PROOF_REJECTED", 403)
        proof = call.proof
        now = time.time()
        self.nonces = {key: expiry for key, expiry in self.nonces.items() if expiry > now}
        if proof.request_uuid in self.nonces:
            return unavailable("NODE_MCP_REQUEST_ALREADY_ADMITTED", 409)
        if len(self.nonces) >= 4096:
            return unavailable("NODE_MCP_BUSY", 429)
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=2)
        except TimeoutError:
            return unavailable("NODE_MCP_BUSY", 429)
        try:
            # Check again after waiting; no await separates this reservation.
            if proof.request_uuid in self.nonces or proof.expires_at <= time.time() or self.closed:
                self.slots.release()
                return unavailable("NODE_MCP_REQUEST_STALE_OR_REPLAYED", 409)
            self.nonces[proof.request_uuid] = proof.expires_at
            upstream = await self.send(call)
        except asyncio.CancelledError:
            self.slots.release()
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, OSError) as error:
            LOG.warning(
                "Node forwarding unavailable module=%s controller_ingress=%s exception=%s cause=%s",
                proof.module,
                self.upstream_socket,
                type(error).__name__,
                type(error.__cause__).__name__,
            )
            self.slots.release()
            return unavailable()
        except BaseException:
            self.slots.release()
            raise
        return await self.response(upstream)


def worker_target(proof: TransportProof, gateway_signature: str = "") -> str:
    del gateway_signature
    if proof.module in SUPERVISOR_MODULES:
        return f"http://{proof.container_name}.{proof.module}/mcp"
    if proof.module == "files":
        return f"http://{proof.container_name}:{proof.port}/mcp"
    raise ValueError("Unknown fixed executor module")
