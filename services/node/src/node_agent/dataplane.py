"""Bounded MCP relay shared by controller ingress and rootless Node Gateway.

Transport signatures bind bytes/selectors; the Hand still owns every effect
decision. There is no Docker socket or management endpoint in this relay.
"""
import asyncio
import base64
import inspect
import time

import httpx
from starlette.responses import JSONResponse

from gateway_runtime.stream import ProxyStreamingResponse
from gateway_runtime.start import PendingProxyStart
from node_protocol.forward import ForwardRejected
from node_protocol.effect import NodeEffectPermit
from node_protocol.files import strict_json
from .runtime_profiles import SUPERVISOR_MODULES


def unavailable(code="NODE_MCP_UNAVAILABLE", status=503):
    return JSONResponse({"code": code}, status_code=status,
                        headers={"cache-control": "no-store", "x-content-type-options": "nosniff"})


class McpRelay:
    def __init__(self, *, verifier, client, admit, upstream_socket=False):
        self.verifier, self.client, self.admit = verifier, client, admit
        self.upstream_socket = upstream_socket
        self.slots = asyncio.Semaphore(32)
        self.responses, self.streams = set(), set()
        self.pending = set()
        self.nonces = {}
        self.closed = False

    async def close(self):
        self.closed = True
        await asyncio.gather(*(start.abort() for start in list(self.pending)), return_exceptions=True)
        await asyncio.gather(*(stream.aclose() for stream in list(self.streams)), return_exceptions=True)
        await self.client.aclose()

    async def forward(self, request):
        if self.closed:
            return unavailable()
        required = ("authorization", "x-briareus-node-proof", "x-briareus-node-signature")
        if (request.scope.get("raw_path") != b"/internal/v1/node/mcp" or request.url.query
            or any(len(request.headers.getlist(name)) != 1 for name in required)
            or len(request.headers.getlist("x-briareus-node-permit")) > 1
            or len(request.headers.getlist("x-briareus-invocation-context")) > 1
            or request.headers.getlist("cookie") or request.headers.getlist("origin")
            or request.headers.getlist("content-type") != ["application/json"]):
            return unavailable("NODE_GATEWAY_PROOF_REQUIRED", 403)
        try:
            async with asyncio.timeout(3):
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 1_048_576:
                        return unavailable("NODE_MCP_BODY_TOO_LARGE", 413)
            body = bytes(body)
            context = request.headers.get("x-briareus-invocation-context", "")
            if request.headers.getlist("x-briareus-invocation-context") and not context:
                raise ForwardRejected("An empty private invocation header is not allowed")
            if len(context) > 11000:
                raise ForwardRejected("Private invocation context exceeds transport bound")
            if context:
                raw_context = base64.b64decode(context, validate=True)
                if not 0 < len(raw_context) <= 8192 or not isinstance(strict_json(raw_context), dict):
                    raise ForwardRejected("Bounded private invocation object required")
            proof = self.verifier.verify(request.headers[required[1]], request.headers[required[2]],
                                         body=body, bearer=request.headers[required[0]],
                                         effect=request.headers.get("x-briareus-node-permit", ""), context=context)
            if proof.effect_digest:
                effect = strict_json(base64.b64decode(request.headers["x-briareus-node-permit"], validate=True))
                effect_permit = NodeEffectPermit.model_validate(effect["permit"])
                if effect_permit.context_digest != proof.context_digest or any(
                    getattr(effect_permit, name) != getattr(proof, name) for name in (
                        "node_uuid", "placement_uuid", "project_uuid", "agent_session_uuid", "request_uuid",
                        "grant_revision", "module", "fingerprint", "body_digest", "bearer_digest")):
                    raise ForwardRejected("Private invocation differs from effect authority")
            elif context:
                raise ForwardRejected("Private invocation requires bound effect authority")
        except (ForwardRejected, TimeoutError, ValueError, KeyError, TypeError):
            return unavailable("NODE_GATEWAY_PROOF_REJECTED", 403)
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
            # No await between duplicate check and reservation; requests queued
            # for a slot must recheck after acquiring it.
            if proof.request_uuid in self.nonces or proof.expires_at <= time.time() or self.closed:
                self.slots.release()
                return unavailable("NODE_MCP_REQUEST_STALE_OR_REPLAYED", 409)
            self.nonces[proof.request_uuid] = proof.expires_at
            target = self.admit(proof)
            if inspect.isawaitable(target):
                async with asyncio.timeout(3):
                    target = await target
            if self.upstream_socket:
                headers = {name: request.headers[name] for name in required}
            else:
                headers = {"authorization": request.headers["authorization"],
                    "x-briareus-project-uuid": str(proof.project_uuid),
                    "x-briareus-agent-session-uuid": str(proof.agent_session_uuid),
                    "x-briareus-grant-revision": str(proof.grant_revision)}
                if proof.protocol_version:
                    headers["mcp-protocol-version"] = proof.protocol_version
                if proof.mcp_session_id:
                    headers["mcp-session-id"] = proof.mcp_session_id
            headers.update({"content-type": "application/json", "accept": "application/json, text/event-stream"})
            if proof.effect_digest:
                headers["x-briareus-node-permit"] = request.headers["x-briareus-node-permit"]
            if context:
                headers["x-briareus-invocation-context"] = context
            upstream_request = self.client.build_request("POST", target, content=body, headers=headers)
            start = PendingProxyStart(self.client, upstream_request)
            self.pending.add(start)
            try:
                upstream = await start.take_response()
            finally:
                self.pending.discard(start)
        except asyncio.CancelledError:
            self.slots.release()
            raise
        except (httpx.HTTPError, TimeoutError, ValueError, OSError):
            self.slots.release()
            return unavailable()
        except BaseException:
            self.slots.release()
            raise
        self.responses.add(upstream)
        stream = ProxyStreamingResponse(upstream, slots=self.slots,
            open_responses=self.responses, tracked_streams=self.streams)
        self.streams.add(stream)
        if self.closed or upstream.status_code not in {200, 202, 204, 400, 401, 403, 404, 409, 422, 429, 503}:
            await stream.aclose()
            return unavailable()
        stream.raw_headers = [(key, value) for key, value in upstream.headers.raw
            if key.lower() in {b"content-type", b"mcp-session-id", b"mcp-protocol-version"}]
        stream.raw_headers += [(b"cache-control", b"no-store"), (b"x-content-type-options", b"nosniff")]
        return stream


def worker_target(proof):
    # The hostname is derived from verified UUIDs and immutable fingerprint.
    # There is no client-supplied URL, IP address, DNS suffix or arbitrary path.
    if proof.module in SUPERVISOR_MODULES:
        return f"http://{proof.container_name}.{proof.module}/mcp"
    if proof.module == "files":
        return f"http://{proof.container_name}:{proof.port}/mcp"
    raise ValueError("Unknown fixed executor module")
