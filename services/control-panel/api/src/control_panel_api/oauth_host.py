"""Host the MCP OAuth facade inside the Control Panel API application."""

from __future__ import annotations

from auth_service.api import build_auth_app
from auth_service.provider import MultiResourceZitadelProvider
from fastapi import FastAPI
from starlette.routing import Route


def install_mcp_oauth(app: FastAPI, provider: MultiResourceZitadelProvider) -> None:
    """Preserve the public OAuth paths and the API's own health/lifespan owner."""
    oauth = build_auth_app(provider)
    app.router.routes.extend(
        route for route in oauth.routes if not isinstance(route, Route) or route.path != "/health"
    )
