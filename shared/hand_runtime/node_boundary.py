"""Request-bound Core evidence, replay rejection and bounded MCP output."""
import asyncio
import base64
import hashlib
import time

from starlette.requests import Request
from starlette.responses import JSONResponse
from node_protocol.effect import EffectRejected
from node_protocol.files import strict_json


class EffectBoundary:
    def __init__(self, app, verifier, *, code="FILES_CURRENT_AUTHORITY_REQUIRED", ready=lambda: True):
        self.app, self.verifier, self.code = app, verifier, code
        self.ready = ready
        self.nonces = {}
        self.slots = asyncio.Semaphore(32)

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)

        async def reject(status=403):
            await JSONResponse({"code": self.code}, status_code=status,
                headers={"cache-control": "no-store"})(scope, receive, send)

        if scope["path"] in {"/health/live", "/health/ready"} and scope["method"] == "GET":
            if scope["path"] == "/health/ready" and not self.ready():
                return await JSONResponse({"state": "starting"}, status_code=503)(scope, receive, send)
            return await JSONResponse({"state": "live", "authorization": "per_request_core_required"})(scope, receive, send)
        if not self.ready():
            return await reject(503)
        if (scope.get("raw_path") != b"/mcp" or scope["method"] != "POST" or scope.get("query_string")
            or request.headers.getlist("content-type") != ["application/json"]
            or request.headers.getlist("cookie") or request.headers.getlist("origin")
            or any(len(request.headers.getlist(name)) != 1 for name in ("authorization", "x-briareus-node-permit"))):
            return await reject()
        try:
            async with asyncio.timeout(3):
                body = bytearray()
                async for chunk in request.stream():
                    if len(body) + len(chunk) > 32768:
                        return await reject(413)
                    body.extend(chunk)
            body = bytes(body)
            permit = self.verifier.verify(request.headers["x-briareus-node-permit"],
                body=body, bearer=request.headers["authorization"])
            contexts = request.headers.getlist("x-briareus-invocation-context")
            context = {}
            if permit.context_digest:
                if len(contexts) != 1 or len(contexts[0]) > 11000:
                    raise ValueError("Private invocation context missing")
                raw = base64.b64decode(contexts[0],validate=True)
                if len(raw)>8192 or hashlib.sha256(raw).hexdigest()!=permit.context_digest:
                    raise ValueError("Wrong invocation context")
                context = strict_json(raw)
                if not isinstance(context,dict):
                    raise ValueError("Private invocation context must be an object")
            elif contexts:
                raise ValueError("Unbound invocation context")
        except (EffectRejected, TimeoutError, ValueError):
            return await reject()
        self.nonces = {key: expiry for key, expiry in self.nonces.items() if expiry > time.time()}
        if permit.request_uuid in self.nonces:
            return await reject(409)
        if len(self.nonces) >= 4096:
            return await reject(429)
        try:
            await asyncio.wait_for(self.slots.acquire(), timeout=1)
        except TimeoutError:
            return await reject(429)
        messages, size = [], 0
        try:
            if permit.request_uuid in self.nonces or permit.expires_at <= time.time():
                return await reject(409)
            self.nonces[permit.request_uuid] = permit.expires_at
            scope = dict(scope, **{"briareus.node_effect": permit,
                "briareus.invocation_context": context})
            delivered = False

            async def replay():
                nonlocal delivered
                if not delivered:
                    delivered = True
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            async def buffer(message):
                nonlocal size
                if message["type"] == "http.response.body":
                    size += len(message.get("body", b""))
                if size > 1_048_576 or len(messages) >= 128:
                    raise ValueError("Bounded executor response required")
                messages.append(message)

            async with asyncio.timeout(max(0, permit.expires_at - time.time())):
                await self.app(scope, replay, buffer)
            # Nothing leaves the executor after its authority expires.
            if permit.expires_at <= time.time():
                return await reject()
            for message in messages:
                await send(message)
        except (TimeoutError, ValueError):
            return await reject()
        finally:
            self.slots.release()

