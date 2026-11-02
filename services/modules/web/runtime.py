from __future__ import annotations

import asyncio as asyncio
import hmac as hmac
import re as re

import httpx as httpx
from mcp.types import CallToolResult
from starlette.requests import Request as Request
from starlette.responses import PlainTextResponse as PlainTextResponse
from starlette.responses import Response as Response
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket as WebSocket

from common.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS as BROWSER_REMOTE_DEBUG_TTL_SECONDS,
)
from common.browser_remote_debug import BrowserRemoteDebugAuthError as BrowserRemoteDebugAuthError
from common.browser_remote_debug import (
    verify_browser_remote_debug_token as verify_browser_remote_debug_token,
)
from common.runtime_annotations import READ_EXTERNAL, WRITE_EXTERNAL
from common.runtime_common import admin_api_client, private_http_app
from common.runtime_policy_contracts import BrowserRuntimePolicy as BrowserRuntimePolicy
from common.settings import (
    AdminApiClientSettings,
    BrowserSettings,
    FileSettings,
    PrivateRuntimeSettings,
)
from common.websocket_proxy import relay_websocket as relay_websocket
from modules.project_runtime.runtime_telemetry import EmptyMcpLifespanState, build_runtime_mcp
from modules.workspace_compat.legacy_store import WorkspaceFileStore
from web_runtime.infrastructure.runtime_routes import WebRuntimeRoutes

from .browser import BrowserManager
from .browser_profile import DEFAULT_BROWSER_DESKTOP_PROFILE, resolve_chromium_gpu_args
from .browser_tools import register_browser_tools
from .devtools_proxy import DevToolsProxyRuntime
from .external_browser_proxy import ExternalBrowserProxyRuntime
from .operator import browser_operator_websocket as browser_operator_websocket
from .transfer_presenter import present_browser

_private_settings = PrivateRuntimeSettings()
_admin_api = admin_api_client(AdminApiClientSettings())
_file_settings = FileSettings()
_browser_settings = BrowserSettings()
_browser_profile = DEFAULT_BROWSER_DESKTOP_PROFILE

mcp, _runtime_telemetry = build_runtime_mcp("web", name="web")
_workspace = WorkspaceFileStore(_file_settings.workspace_root)
_browser = BrowserManager(
    workspace=_workspace,
    profile_dir=_browser_settings.profile_dir,
    executable_path=_browser_settings.executable_path,
    headless=_browser_profile.headless,
    timeout_ms=_browser_settings.timeout_ms,
    viewport_width=_browser_profile.viewport_width,
    viewport_height=_browser_profile.viewport_height,
    screen_width=_browser_profile.screen_width,
    screen_height=_browser_profile.screen_height,
    locale=_browser_profile.locale,
    accept_language=_browser_profile.accept_language,
    display=_browser_profile.display,
    color_depth=_browser_profile.color_depth,
    xvfb_enabled=_browser_profile.xvfb_enabled,
    timezone=_browser_settings.timezone,
    posix_locale=_browser_profile.posix_locale,
    chromium_args=(*_browser_profile.chromium_args, *resolve_chromium_gpu_args()),
    max_snapshot_text_chars=_browser_settings.max_snapshot_text_chars,
    max_snapshot_elements=_browser_settings.max_snapshot_elements,
)

register_browser_tools(
    mcp,
    READ_EXTERNAL,
    WRITE_EXTERNAL,
    browser=_browser,
)

_devtools = DevToolsProxyRuntime[EmptyMcpLifespanState](_browser, _browser_settings)
mcp.mount(_devtools.server, namespace="devtools")


_runtime_routes = WebRuntimeRoutes(_admin_api, _browser)
_external_browser_policy = _runtime_routes.external_browser_policy


_external_browser = ExternalBrowserProxyRuntime[EmptyMcpLifespanState](_external_browser_policy)
mcp.mount(_external_browser.server, namespace="external")


@mcp.tool(title="External browser status", annotations=READ_EXTERNAL)
async def browser_external_status() -> CallToolResult:
    """Report configuration and live state for the external Playwright MCP bridge."""
    return present_browser(await _external_browser.status())


@mcp.tool(title="Connect external browser", annotations=WRITE_EXTERNAL)
async def browser_external_connect() -> CallToolResult:
    """Connect the configured external Playwright MCP server and keep the session alive."""
    return present_browser(await _external_browser.connect())


@mcp.tool(title="Disconnect external browser", annotations=WRITE_EXTERNAL)
async def browser_external_disconnect() -> CallToolResult:
    """Close the persistent external Playwright MCP session without stopping Chrome."""
    return present_browser(await _external_browser.disconnect())


@mcp.tool(title="Reset external browser", annotations=WRITE_EXTERNAL)
async def browser_external_reset() -> CallToolResult:
    """Reset the external MCP session and reconnect using current Admin settings."""
    return present_browser(await _external_browser.reset())


app = _runtime_telemetry.attach(private_http_app(mcp, _private_settings))


_private_service_authorized = _runtime_routes.private_service_authorized


_cdp_ws = _runtime_routes.cdp_websocket


_cdp_ui_http = _runtime_routes.cdp_frontend


_operator_ws = _runtime_routes.operator_websocket


app.router.routes.extend(
    [
        Route(
            "/cdp-ui/{token}/page/{target_id}/{asset_path:path}",
            _cdp_ui_http,
            methods=["GET"],
        ),
        WebSocketRoute("/operator/ws", _operator_ws),
        WebSocketRoute("/cdp/page/{target_id}", _cdp_ws),
    ]
)
