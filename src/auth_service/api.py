from __future__ import annotations

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .oauth_routes import OAuthRoutes
from .provider import MultiResourceZitadelProvider


def build_auth_app(provider: MultiResourceZitadelProvider) -> Starlette:
    async def health(_request: Request) -> Response:
        return JSONResponse({"status": "ok"})

    adapters = OAuthRoutes(provider)
    routes = [route for route in provider.get_routes(mcp_path="/mcp") if route.path != "/revoke"]
    routes.append(Route("/revoke", adapters.revoke, methods=["POST"]))
    routes.append(Route("/introspect", adapters.introspect, methods=["POST"]))
    routes.append(Route("/health", health, methods=["GET"]))
    return Starlette(routes=routes)
