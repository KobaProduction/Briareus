from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from briareus_control_panel_client.control_panel_client import (
    ControlPanelClient,
    ControlPanelClientError,
)
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_mcp_policy import McpRuntimePolicy
from briareus_mcp_policy_client import mcp_runtime_policy
from briareus_oidc import OidcTokenVerifier
from briareus_service_discovery import ServiceDiscovery, ServiceRegistry
from briareus_telemetry.observability import announce_runtime_started, build_observability
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.websockets import WebSocket

from .browser_sockets import management_websocket_routes, relay_panel_websocket
from .gateway_settings import GatewayAuthSettings
from .models import GatewayHealth
from .reverse_proxy import ReverseProxy
from .service_routes import ServiceMcpRoutes
from .settings import GatewaySettings

_settings = GatewaySettings()
_auth_settings = GatewayAuthSettings()
_auth_settings.validate_bootstrap()
_management_settings = ControlPanelClientSettings()
_management = ControlPanelClient(_management_settings)
_observability = build_observability("gateway")
announce_runtime_started(_observability, "gateway")
_panel_token_verifier = OidcTokenVerifier(_auth_settings) if _auth_settings.enabled else None
_service_discovery = ServiceDiscovery(ServiceRegistry())
_PROXY_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def _backend_timeout_seconds() -> float:
    try:
        policy = await asyncio.wait_for(
            asyncio.to_thread(mcp_runtime_policy, _management), timeout=1.0
        )
    except (TimeoutError, ControlPanelClientError, ValueError):
        policy = McpRuntimePolicy()
    return float(policy.call_timeout_seconds)


_mcp_routes = ServiceMcpRoutes(
    _service_discovery, _settings, _auth_settings, _backend_timeout_seconds
)
_management_api_proxy = ReverseProxy(
    _management_settings.url,
    backend_name="management",
    public_prefix="/api",
    upstream_prefix="/admin/api",
)
_management_ui_proxy = ReverseProxy(
    "http://control-panel-ui:8080",
    backend_name="management-ui",
    public_prefix="/admin",
)


@asynccontextmanager
async def _gateway_lifespan(_app: Starlette) -> AsyncIterator[None]:
    async with _mcp_routes.lifespan():
        try:
            yield
        finally:
            await asyncio.gather(
                _management_api_proxy.close(),
                _management_ui_proxy.close(),
                _service_discovery.close(),
            )


async def _management_websocket(websocket: WebSocket, path: str) -> None:
    await relay_panel_websocket(
        websocket,
        path,
        verifier=_panel_token_verifier,
        public_base_url=_auth_settings.public_base_url,
        backend_base_url=_management_settings.url,
    )


async def _removed_admin_api(_request: Request) -> PlainTextResponse:
    return PlainTextResponse("Not Found", status_code=404)


async def _health(_request: Request) -> JSONResponse:
    return JSONResponse(
        GatewayHealth(node=_auth_settings.node_id, commit=_settings.build_sha).to_json()
    )


app = Starlette(lifespan=_gateway_lifespan)
app.router.routes.extend(management_websocket_routes(_management_websocket))
app.add_route("/health", _health, methods=["GET"])
app.add_route("/api", _management_api_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/api/{path:path}", _management_api_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/api", _removed_admin_api, methods=_PROXY_METHODS)
app.add_route("/admin/api/{path:path}", _removed_admin_api, methods=_PROXY_METHODS)
app.add_route("/admin", _management_ui_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/{path:path}", _management_ui_proxy.handle, methods=_PROXY_METHODS)
app.mount("/", _mcp_routes)
