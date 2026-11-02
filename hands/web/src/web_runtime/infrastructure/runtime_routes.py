"""Web-owned private CDP and operator route bindings for existing entrypoints."""

from __future__ import annotations

import asyncio
import hmac
import re

import httpx
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.websockets import WebSocket

from service_runtime.admin_api_client import AdminApiClient
from service_runtime.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS,
    BrowserRemoteDebugAuthError,
    verify_browser_remote_debug_token,
)
from service_runtime.runtime_policy_contracts import BrowserRuntimePolicy
from service_runtime.websocket_proxy import relay_websocket
from web_runtime.infrastructure.operator_runtime import OperatorBrowserRuntime
from web_runtime.operator import browser_operator_websocket


class WebRuntimeRoutes:
    def __init__(self, admin_api: AdminApiClient, browser: OperatorBrowserRuntime) -> None:
        self._admin_api = admin_api
        self._browser = browser

    async def external_browser_policy(self) -> BrowserRuntimePolicy:
        return await asyncio.to_thread(self._admin_api.browser_runtime_policy)

    def private_service_authorized(self, websocket: WebSocket) -> bool:
        authorization = websocket.headers.get("authorization", "")
        scheme, _, token = authorization.partition(" ")
        supplied = token.strip() if scheme.casefold() == "bearer" else ""
        expected = self._admin_api.service_token
        return bool(supplied and expected and hmac.compare_digest(supplied, expected))

    async def cdp_websocket(self, websocket: WebSocket) -> None:
        if not self.private_service_authorized(websocket):
            await websocket.close(code=4401)
            return
        target_id = str(websocket.path_params.get("target_id") or "")
        if re.fullmatch("[A-Za-z0-9_-]{1,128}", target_id) is None:
            await websocket.close(code=4400)
            return
        await relay_websocket(
            websocket, f"ws://127.0.0.1:9222/devtools/page/{target_id}", origin=None
        )

    async def cdp_frontend(self, request: Request) -> Response:
        token = str(request.path_params.get("token") or "")
        target_id = str(request.path_params.get("target_id") or "")
        asset_path = str(request.path_params.get("asset_path") or "")
        try:
            verify_browser_remote_debug_token(
                token,
                self._admin_api.service_token,
                None,
                target_id,
                max_age_seconds=BROWSER_REMOTE_DEBUG_TTL_SECONDS,
            )
        except BrowserRemoteDebugAuthError:
            return PlainTextResponse("Unauthorized", status_code=401)
        if not asset_path.startswith("devtools/") or ".." in asset_path.split("/"):
            return PlainTextResponse("Not Found", status_code=404)
        target = f"http://127.0.0.1:9222/{asset_path}"
        if request.url.query:
            target += "?" + request.url.query
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as client:
                upstream = await client.get(target)
        except httpx.RequestError:
            return PlainTextResponse("Chrome DevTools frontend unavailable", status_code=502)
        body = upstream.content
        content_type = upstream.headers.get("content-type", "application/octet-stream")
        if any(kind in content_type for kind in ("text/", "javascript", "json")):
            try:
                text = body.decode("utf-8")
            except UnicodeDecodeError:
                pass
            else:
                public_prefix = f"/v1/browser/devtools/{token}/page/{target_id}"
                text = text.replace("/devtools/", f"{public_prefix}/devtools/")
                body = text.encode("utf-8")
        headers = {
            key: value
            for key, value in upstream.headers.items()
            if key.casefold()
            not in {"content-length", "content-encoding", "transfer-encoding", "connection"}
        }
        headers["cache-control"] = "no-store"
        return Response(body, status_code=upstream.status_code, headers=headers, media_type=None)

    async def operator_websocket(self, websocket: WebSocket) -> None:
        await browser_operator_websocket(
            websocket, browser=self._browser, service_token=self._admin_api.service_token
        )
