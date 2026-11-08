from __future__ import annotations

import asyncio
import hmac
import logging
import re
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_browser_policy_client import browser_runtime_policy
from briareus_control_panel_client.settings import ControlPanelClientSettings
from briareus_hand_runtime.runtime_common import (
    build_private_mcp,
    management_client,
    private_http_app,
)
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_json_values import JsonObject
from briareus_tool_annotations import READ_EXTERNAL, WRITE_EXTERNAL
from briareus_websocket_transport.websocket_proxy import relay_websocket
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket

from briareus_playwright.session import create_browser_session

from .browser_tools import register_browser_tools
from .external import ExternalBrowserProxyRuntime
from .operator import browser_operator_websocket

_private_settings = PrivateRuntimeSettings()
_management = management_client(ControlPanelClientSettings())
_session = create_browser_session()
_browser_settings = _session.settings
_browser = _session.browser
mcp = build_private_mcp("playwright", _management)
register_browser_tools(mcp, READ_EXTERNAL, WRITE_EXTERNAL, browser=_browser)


async def _external_browser_policy() -> BrowserRuntimePolicy:
    return await asyncio.to_thread(browser_runtime_policy, _management)


_external_browser = ExternalBrowserProxyRuntime(_external_browser_policy)
mcp.mount(_external_browser.server, namespace="external")


@mcp.tool(title="External Playwright status", annotations=READ_EXTERNAL)
async def browser_external_status() -> JsonObject:
    return await _external_browser.status()


@mcp.tool(title="Connect external Playwright", annotations=WRITE_EXTERNAL)
async def browser_external_connect() -> JsonObject:
    return await _external_browser.connect()


@mcp.tool(title="Disconnect external Playwright", annotations=WRITE_EXTERNAL)
async def browser_external_disconnect() -> JsonObject:
    return await _external_browser.disconnect()


@mcp.tool(title="Reset external Playwright", annotations=WRITE_EXTERNAL)
async def browser_external_reset() -> JsonObject:
    return await _external_browser.reset()


app = private_http_app(mcp, _private_settings)


def _private_service_authorized(websocket: WebSocket) -> bool:
    authorization = websocket.headers.get("authorization", "")
    scheme, _, token = authorization.partition(" ")
    supplied = token.strip() if scheme.casefold() == "bearer" else ""
    expected = _management.service_token
    return bool(supplied and expected and hmac.compare_digest(supplied, expected))


async def _cdp_ws(websocket: WebSocket) -> None:
    if not _private_service_authorized(websocket):
        await websocket.close(code=4401)
        return
    target_id = str(websocket.path_params.get("target_id") or "")
    if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id) is None:
        await websocket.close(code=4400)
        return
    async with _browser.target_operation(target_id):
        await relay_websocket(
            websocket,
            f"{_browser_settings.cdp_url.replace('http://', 'ws://').replace('https://', 'wss://')}/devtools/page/{target_id}",
            origin=None,
        )


async def _operator_ws(websocket: WebSocket) -> None:
    await browser_operator_websocket(
        websocket,
        browser=_browser,
        service_token=_management.service_token,
    )


app.router.routes.extend(
    [
        WebSocketRoute("/operator/ws", _operator_ws),
        WebSocketRoute("/cdp/page/{target_id}", _cdp_ws),
    ]
)


_previous_lifespan = app.router.lifespan_context


async def _idle_cleanup() -> None:
    while True:
        await asyncio.sleep(10)
        try:
            await _browser.cleanup_idle_tabs()
        except Exception:
            logging.getLogger(__name__).warning("Browser idle tab cleanup failed")


@asynccontextmanager
async def _browser_lifespan(application: Starlette) -> AsyncIterator[None]:
    async with _previous_lifespan(application):
        task = asyncio.create_task(_idle_cleanup(), name="browser-idle-tabs")
        try:
            yield
        finally:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
            await _browser.stop_background_tasks()


app.router.lifespan_context = _browser_lifespan
