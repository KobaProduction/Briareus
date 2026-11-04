from __future__ import annotations

import asyncio
import platform
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from datetime import UTC, datetime

from briareus_control_panel_client.control_panel_client import (
    ControlPanelClient,
    ControlPanelClientError,
)
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_json_values import JsonObject
from briareus_mcp_policy import McpRuntimePolicy
from briareus_mcp_policy_client import mcp_runtime_policy
from briareus_mcp_resources import MCP_SURFACE_PATHS
from briareus_telemetry.observability import announce_runtime_started, build_observability
from briareus_tool_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, READ_ONLY_LOCAL
from briareus_zitadel_tokens import ZitadelTokenVerifier
from fastmcp import FastMCP
from fastmcp.server.auth import RemoteAuthProvider
from fastmcp.server.providers.proxy import FastMCPProxy
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse
from starlette.routing import BaseRoute
from starlette.websockets import WebSocket

from gateway.gateway_settings import GatewayAuthSettings
from gateway.settings import GatewaySettings

from . import __version__
from .auth_surfaces import build_surface_auth as _build_surface_auth
from .backend_router import BackendDescriptor, BackendRouter
from .backend_sessions import ProxyClientPool
from .browser_sockets import management_websocket_routes, relay_panel_websocket
from .models import GatewayBuildInfo, GatewayCapabilities, GatewayPing
from .reverse_proxy import ReverseProxy

_STARTED_AT = datetime.now(UTC).isoformat()
_observability = build_observability("gateway")
announce_runtime_started(_observability, "gateway")
_CONTROL_PANEL_UI_URL = "http://control-panel-ui:8080"
_PROXY_METHODS = ["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"]


async def _backend_timeout_seconds() -> float:
    try:
        policy = await asyncio.wait_for(
            asyncio.to_thread(mcp_runtime_policy, _management),
            timeout=1.0,
        )
    except (TimeoutError, ControlPanelClientError, ValueError):
        policy = McpRuntimePolicy()
    return float(policy.call_timeout_seconds)


def _proxy_target(name: str, target: str | FastMCP[None]) -> FastMCP[None]:
    pool = ProxyClientPool(
        target,
        name=name,
        timeout_provider=_backend_timeout_seconds,
        size=2,
    )
    return FastMCPProxy(
        client_factory=pool.acquire,
        name=f"{name}-backend",
        lifespan=pool.lifespan,
    )


def _proxy(name: str, url: str) -> FastMCP[None]:
    return _proxy_target(name, url)


def _public_facade(
    name: str,
    backend_name: str,
    backend_url: str,
    auth_by_surface: dict[str, RemoteAuthProvider],
) -> FastMCP[None]:
    surface = FastMCP(
        name,
        version=__version__,
        auth=auth_by_surface.get(name),
    )
    surface.mount(server=_proxy(backend_name, backend_url))
    return surface


_settings = GatewaySettings()
_auth_settings = GatewayAuthSettings()
_management_settings = ControlPanelClientSettings()
_BACKENDS = _settings.backends
_management = ControlPanelClient(_management_settings)
_auth_by_surface = _build_surface_auth(_auth_settings)
_panel_token_verifier = ZitadelTokenVerifier(_auth_settings) if _auth_settings.enabled else None

_backend_router = BackendRouter(
    (
        BackendDescriptor(
            "github",
            _BACKENDS["github"],
            MCP_SURFACE_PATHS["github"],
            "GitHub repositories, pull requests, issues, Actions and reviews",
        ),
        BackendDescriptor(
            "gitlab",
            _BACKENDS["gitlab"],
            MCP_SURFACE_PATHS["gitlab"],
            "GitLab projects, repositories, merge requests, issues and CI",
        ),
        BackendDescriptor(
            "server",
            _BACKENDS["server"],
            MCP_SURFACE_PATHS["server"],
            "Server filesystem, workspaces, commands and long-running jobs",
        ),
        BackendDescriptor(
            "web",
            _BACKENDS["web"],
            MCP_SURFACE_PATHS["web"],
            "Persistent browser automation and browser downloads",
        ),
        BackendDescriptor(
            "analysis",
            _BACKENDS["analysis"],
            MCP_SURFACE_PATHS["analysis"],
            "General-purpose structured analysis surface",
        ),
        BackendDescriptor(
            "ghidra",
            _BACKENDS["ghidra"],
            "",
            "Private native analysis backend",
        ),
        BackendDescriptor(
            "observability",
            _BACKENDS["observability"],
            MCP_SURFACE_PATHS["observability"],
            "Unified read-only infrastructure state, logs, traces, metrics and deployments",
        ),
    ),
    timeout_provider=_backend_timeout_seconds,
)

mcp = FastMCP(
    "Briareus",
    version=__version__,
    instructions=(
        "Universal MCP map and bridge. Dedicated backends are not automatically "
        "published on this root surface. Use bridge_backends to inspect availability, "
        "bridge_tools to fetch one backend tool catalog/signatures, and bridge_call "
        "to forward a call to a selected backend."
    ),
    auth=_auth_by_surface.get("root"),
)

github_surface = _public_facade(
    "github",
    "github",
    _BACKENDS["github"],
    _auth_by_surface,
)
gitlab_surface = _public_facade(
    "gitlab",
    "gitlab",
    _BACKENDS["gitlab"],
    _auth_by_surface,
)
server_surface = _public_facade(
    "server",
    "server",
    _BACKENDS["server"],
    _auth_by_surface,
)
web_surface = _public_facade(
    "web",
    "web",
    _BACKENDS["web"],
    _auth_by_surface,
)
analysis_surface = _public_facade(
    "analysis",
    "analysis",
    _BACKENDS["analysis"],
    _auth_by_surface,
)
observability_surface = _public_facade(
    "observability",
    "observability",
    _BACKENDS["observability"],
    _auth_by_surface,
)


@mcp.tool(title="Bridge ping", annotations=READ_ONLY_LOCAL)
def bridge_ping() -> JsonObject:
    return GatewayPing(version=__version__, time=datetime.now(UTC).isoformat()).to_json()


@mcp.tool(title="Bridge build info", annotations=READ_ONLY_LOCAL)
def bridge_build_info() -> JsonObject:
    return GatewayBuildInfo(
        version=__version__,
        commit=_settings.build_sha,
        built_at=_settings.build_time,
        started_at=_STARTED_AT,
        python=platform.python_version(),
    ).to_json()


@mcp.tool(title="Bridge backends", annotations=READ_EXTERNAL)
async def bridge_backends() -> JsonObject:
    """List public/private bridge backends with live availability and tool counts."""
    return await _backend_router.describe()


@mcp.tool(title="Bridge backend tools", annotations=READ_EXTERNAL)
async def bridge_tools(backend: str, refresh: bool = False) -> JsonObject:
    """Fetch one backend tool catalog and signatures without publishing it at root."""
    return await _backend_router.tools(backend, refresh=refresh)


@mcp.tool(title="Bridge forward call", annotations=DESTRUCTIVE_EXTERNAL)
async def bridge_call(
    backend: str,
    tool_name: str,
    arguments: JsonObject | None = None,
) -> JsonObject:
    """Forward one tool call to a selected backend without adding bridge metadata."""
    return await _backend_router.call(backend, tool_name, arguments)


@mcp.tool(title="Bridge capabilities", annotations=READ_ONLY_LOCAL)
def bridge_capabilities() -> JsonObject:
    return GatewayCapabilities(
        backends=sorted(_BACKENDS),
        public_surfaces=[*MCP_SURFACE_PATHS.values(), "/admin", "/api"],
        features=[
            "mcp",
            "streamable-http",
            "gateway",
            "central-oauth",
            "backend-map",
            "backend-signatures",
            "generic-forwarding",
            "account-management",
            "multi-account-github",
            "multi-account-gitlab",
            "server",
            "web",
            "browser",
            "playwright",
            "analysis",
            "terminal",
            "jobs",
            "observability",
            "multi-account-signoz",
            "multi-account-coolify",
            "admin",
        ],
    ).to_json()


_allowed_hosts = list(_settings.http.allowed_hosts)
_allowed_origins = list(_settings.http.allowed_origins)


def _http_app(surface: FastMCP[None]) -> Starlette:
    return surface.http_app(
        path="/mcp",
        allowed_hosts=_allowed_hosts,
        allowed_origins=_allowed_origins,
    )


def _resource_discovery_routes() -> list[BaseRoute]:
    routes: list[BaseRoute] = []
    seen_paths: set[str] = set()
    for auth in _auth_by_surface.values():
        for route in auth.get_well_known_routes(mcp_path="/mcp"):
            path = getattr(route, "path", "")
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            routes.append(route)
    return routes


_root_http_app = _http_app(mcp)
_github_http_app = _http_app(github_surface)
_gitlab_http_app = _http_app(gitlab_surface)
_server_http_app = _http_app(server_surface)
_web_http_app = _http_app(web_surface)
_analysis_http_app = _http_app(analysis_surface)
_observability_http_app = _http_app(observability_surface)

_MCP_HTTP_APPS = (
    _root_http_app,
    _github_http_app,
    _gitlab_http_app,
    _server_http_app,
    _web_http_app,
    _analysis_http_app,
    _observability_http_app,
)
_MCP_LIFESPANS = tuple(mcp_app.router.lifespan_context for mcp_app in _MCP_HTTP_APPS)
_REVERSE_PROXIES: list[ReverseProxy] = []


@asynccontextmanager
async def _gateway_lifespan(app: Starlette) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        for lifespan in _MCP_LIFESPANS:
            await stack.enter_async_context(lifespan(app))
        try:
            yield
        finally:
            await _backend_router.close()
            await asyncio.gather(
                *(proxy.close() for proxy in _REVERSE_PROXIES),
                return_exceptions=True,
            )


app = Starlette(lifespan=_gateway_lifespan)

for _route in _resource_discovery_routes():
    app.router.routes.append(_route)


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


_management_api_proxy = ReverseProxy(
    _management_settings.url,
    backend_name="management",
    public_prefix="/api",
    upstream_prefix="/admin/api",
)
_management_ui_proxy = ReverseProxy(
    _CONTROL_PANEL_UI_URL,
    backend_name="management-ui",
    public_prefix="/admin",
)
_REVERSE_PROXIES.extend([_management_api_proxy, _management_ui_proxy])
app.router.routes.extend(management_websocket_routes(_management_websocket))
app.add_route("/api", _management_api_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/api/{path:path}", _management_api_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/api", _removed_admin_api, methods=_PROXY_METHODS)
app.add_route("/admin/api/{path:path}", _removed_admin_api, methods=_PROXY_METHODS)
app.add_route("/admin", _management_ui_proxy.handle, methods=_PROXY_METHODS)
app.add_route("/admin/{path:path}", _management_ui_proxy.handle, methods=_PROXY_METHODS)

app.mount("/github", _github_http_app)
app.mount("/gitlab", _gitlab_http_app)
app.mount("/server", _server_http_app)
app.mount("/web", _web_http_app)
app.mount("/analysis", _analysis_http_app)
app.mount("/observability", _observability_http_app)
app.mount("/", _root_http_app)
