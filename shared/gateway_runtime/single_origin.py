"""P0 single public Gateway route contract (SOURCE only, deliberately closed).

No trusted auth/JTI, C2 owner peers, Panel/API upstream transports, WebSocket
upgrade/drain or streamable HTTP/SSE path have been accepted for this origin.
Until independently verified, these exact paths return a bounded unavailable
response and never proxy private services or advertise bogus OAuth metadata.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Literal

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import BaseRoute, Route
from starlette.types import ASGIApp, Receive, Scope, Send

PUBLIC_ORIGIN = "https://briareus.koba-nexus.ru"
PUBLIC_HOST = "briareus.koba-nexus.ru"
MCP_MODULES: tuple[Literal["files", "web", "terminal", "svc", "infrastructure", "reverse"], ...] = (
    "files",
    "web",
    "terminal",
    "svc",
    "infrastructure",
    "reverse",
)
MCP_ENDPOINTS: dict[str, str] = {name: f"/hands/{name}/mcp" for name in MCP_MODULES}

# This is an allowlist, NOT an open-ended /hands/{module} proxy. The only
# source-accepted path for Files is /hands/files/mcp (plural).
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def unavailable(_request: Request) -> Response:
    """No streaming, echo, raw URL, credentials or arbitrary exception text."""
    return JSONResponse(
        {"code": "GATEWAY_C2_RELEASE_UNAVAILABLE"},
        status_code=503,
        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
    )


def unavailable_routes(endpoints: Iterable[str]) -> list[BaseRoute]:
    """Static closed P0 namespaces; never mount historical MCP aliases."""
    return [
        Route("/", unavailable, methods=_METHODS),
        Route("/panel", unavailable, methods=_METHODS),
        Route("/panel/{path:path}", unavailable, methods=_METHODS),
        Route("/api", unavailable, methods=_METHODS),
        Route("/api/{path:path}", unavailable, methods=_METHODS),
        Route("/.well-known/oauth-authorization-server", unavailable, methods=_METHODS),
        Route("/.well-known/oauth-protected-resource", unavailable, methods=_METHODS),
        Route("/.well-known/openid-configuration", unavailable, methods=_METHODS),
        Route("/oauth/{path:path}", unavailable, methods=_METHODS),
        *[Route(path, unavailable, methods=_METHODS) for path in endpoints],
    ]


class _UnavailableRoutes:
    def __init__(self, endpoints: Iterable[str]) -> None:
        self._endpoints = endpoints

    def __call__(self) -> list[BaseRoute]:
        return unavailable_routes(self._endpoints)


def _allowed_headers(
    headers: list[tuple[bytes, bytes]], public_host: str, public_origin: str
) -> tuple[bool, bool]:
    # Lossy decoding must never turn malformed headers into a trusted host.
    try:
        hosts = [v.decode("ascii").casefold() for k, v in headers if k.lower() == b"host"]
        origins = [v.decode("ascii") for k, v in headers if k.lower() == b"origin"]
    except UnicodeDecodeError:
        hosts = []
        origins = ["malformed-origin"]
    host_allowed = len(hosts) == 1 and hosts[0] in {public_host, f"{public_host}:443"}
    origin_allowed = len(origins) <= 1 and (not origins or origins[0] == public_origin)
    return host_allowed, origin_allowed


class SingleOriginGuard:
    """Reject origin/Host spoofing before any later authenticated route install.

    This source guard never trusts x-forwarded-*, a caller-supplied JSON
    origin, or an arbitrary wildcard CORS entry. The accepted Traefik TLS
    termination and service-identity boundary must be separately verified.
    """

    _public_host = PUBLIC_HOST
    _public_origin = PUBLIC_ORIGIN

    def __init__(self, app: ASGIApp, *, allow_verified_websocket: bool = False) -> None:
        self.app = app
        self.allow_verified_websocket = allow_verified_websocket

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        host_allowed, origin_allowed = _allowed_headers(
            scope.get("headers", []), self._public_host, self._public_origin
        )
        if not host_allowed or not origin_allowed:
            if scope["type"] == "websocket":
                await send({"type": "websocket.close", "code": 1008})
            else:
                await JSONResponse(
                    {"code": "GATEWAY_ORIGIN_REJECTED"},
                    status_code=421 if not host_allowed else 403,
                    headers={"Cache-Control": "no-store"},
                )(scope, receive, send)
            return
        # A WebSocket upgrade must not silently become a public alternative
        # to signed MCP SSE/streamable HTTP and gateway C2 user approval.
        if scope["type"] == "websocket" and not self.allow_verified_websocket:
            await send({"type": "websocket.close", "code": 1008})
            return
        await self.app(scope, receive, send)
