"""P0 single public Gateway route contract (SOURCE only, deliberately closed).

No trusted auth/JTI, C2 owner peers, Panel/API upstream transports, WebSocket
upgrade/drain or streamable HTTP/SSE path have been accepted for this origin.
Until independently verified, these exact paths return a bounded unavailable
response and never proxy private services or advertise bogus OAuth metadata.
"""

from __future__ import annotations

import os
from typing import Literal

from starlette.requests import Request as Request
from starlette.responses import JSONResponse as JSONResponse
from starlette.responses import Response as Response
from starlette.routing import BaseRoute as BaseRoute
from starlette.routing import Route as Route
from starlette.types import ASGIApp as ASGIApp
from starlette.types import Receive as Receive
from starlette.types import Scope as Scope
from starlette.types import Send as Send

from gateway_runtime.single_origin import SingleOriginGuard as _SharedSingleOriginGuard
from gateway_runtime.single_origin import _UnavailableRoutes
from gateway_runtime.single_origin import unavailable as unavailable

PUBLIC_HOST = (
    "127.0.0.1" if os.environ.get("BRIAREUS_LOCAL_TESTING") == "1" else "briareus.koba-nexus.ru"
)
PUBLIC_ORIGIN = "https://" + PUBLIC_HOST
MCP_MODULES: tuple[
    Literal["files", "web", "terminal", "svc", "infrastructure", "reverse", "serena"], ...
] = (
    "files",
    "web",
    "terminal",
    "svc",
    "infrastructure",
    "reverse",
    "serena",
)
MCP_ENDPOINTS: dict[str, str] = {name: f"/hands/{name}/mcp" for name in MCP_MODULES}

# This is an allowlist, NOT an open-ended /hands/{module} proxy. The only
# source-accepted path for Files is /hands/files/mcp (plural).
_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


unavailable_routes = _UnavailableRoutes(MCP_ENDPOINTS.values())


class SingleOriginGuard(_SharedSingleOriginGuard):
    """Preserve this entrypoint's public host and origin policy."""

    _public_host = PUBLIC_HOST
    _public_origin = PUBLIC_ORIGIN
