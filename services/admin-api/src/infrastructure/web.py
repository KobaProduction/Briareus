from __future__ import annotations

from typing import NamedTuple

import httpx
from application.browser_inputs import BrowserPageSelection, BrowserThemePayload, ViewportPayload
from fastmcp import Client
from fastmcp.client.transports import ClientTransport
from mcp.types import CallToolRequestParams
from pydantic import BaseModel

from common.browser_contracts import BrowserStatus, DebugTarget, ExternalBrowserStatus, PageSummary
from common.mcp_client_pool import PersistentMcpClientPool
from common.mcp_replies import decode_mcp_reply

_DEFAULT_WEB_MCP_URL = "http://web:8000/mcp"


class BrowserAssetResponse(NamedTuple):
    status: int
    headers: dict[str, str]
    body: bytes


class WebAdminClient:
    def __init__(self, url: str = _DEFAULT_WEB_MCP_URL, *, timeout_seconds: float = 30.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._pool = PersistentMcpClientPool(
            lambda: Client[ClientTransport](self.url, timeout=self.timeout_seconds),
            name="admin-api-web",
            size=2,
        )
        self._http = httpx.AsyncClient(
            base_url="http://web:8000",
            follow_redirects=False,
            timeout=10.0,
            limits=httpx.Limits(max_connections=16, max_keepalive_connections=8),
        )

    async def _call[T: BaseModel](
        self, tool: str, response_model: type[T], arguments: BaseModel | None = None
    ) -> T:
        result = await self._pool.call_tool(
            CallToolRequestParams(
                name=tool,
                arguments=arguments.model_dump(mode="json") if arguments is not None else {},
            ),
            timeout_seconds=self.timeout_seconds,
        )
        return decode_mcp_reply(result, response_model, context=f"web admin {tool}")

    async def status(self) -> BrowserStatus:
        return await self._call("browser_status", BrowserStatus)

    async def set_viewport(self, page_id: str, width: int, height: int) -> PageSummary:
        return await self._call(
            "browser_set_viewport",
            PageSummary,
            ViewportPayload(page_id=page_id, width=width, height=height),
        )

    async def set_theme(self, color_scheme: str) -> BrowserStatus:
        return await self._call(
            "browser_set_theme", BrowserStatus, BrowserThemePayload(color_scheme=color_scheme)
        )

    async def debug_target(self, page_id: str) -> DebugTarget:
        return await self._call(
            "browser_debug_target", DebugTarget, BrowserPageSelection(page_id=page_id)
        )

    async def external_status(self) -> ExternalBrowserStatus:
        return await self._call("browser_external_status", ExternalBrowserStatus)

    async def external_connect(self) -> ExternalBrowserStatus:
        return await self._call("browser_external_connect", ExternalBrowserStatus)

    async def external_disconnect(self) -> ExternalBrowserStatus:
        return await self._call("browser_external_disconnect", ExternalBrowserStatus)

    async def external_reset(self) -> ExternalBrowserStatus:
        return await self._call("browser_external_reset", ExternalBrowserStatus)

    async def devtools_asset(
        self,
        token: str,
        target_id: str,
        asset_path: str,
        query: str = "",
    ) -> BrowserAssetResponse:
        path = f"/cdp-ui/{token}/page/{target_id}/{asset_path}"
        if query:
            path += f"?{query}"
        response = await self._http.get(path)
        headers = {
            key: value
            for key, value in response.headers.items()
            if key.casefold()
            not in {"content-length", "content-encoding", "transfer-encoding", "connection"}
        }
        return BrowserAssetResponse(response.status_code, headers, response.content)

    async def close(self) -> None:
        await self._pool.close()
        await self._http.aclose()
