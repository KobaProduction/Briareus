from __future__ import annotations

from briareus_json_values import JsonObject, JsonValue, json_loads, json_object, json_value
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from control_panel_api.domain.admin_data.browser import (
    BrowserDebugTarget,
    BrowserStatus,
    BrowserStopResult,
    BrowserViewportResult,
    ExternalBrowserAction,
    ExternalBrowserStatus,
)

_DEFAULT_WEB_MCP_URL = "http://playwright-mcp-hand:8000/mcp"


def _decode_result(value: object) -> JsonValue:
    current: object = value
    for _ in range(8):
        if isinstance(current, dict):
            if "result" in current:
                current = current["result"]
                continue
            if "data" in current:
                current = current["data"]
                continue
            return json_value(current, context="web admin result")
        if isinstance(current, str):
            try:
                current = json_loads(current, context="web admin result")
            except ValueError:
                return current
            continue
        return json_value(current, context="web admin result")
    return json_value(current, context="web admin result")


def _decode_call_result(result: CallToolResult) -> JsonValue | None:
    candidates: list[object | None] = [result.structured_content, result.data]
    candidates.extend(block.text for block in result.content if block.type == "text")
    for candidate in candidates:
        if candidate is not None:
            return _decode_result(candidate)
    return None


class WebAdminClient:
    def __init__(self, url: str = _DEFAULT_WEB_MCP_URL, *, timeout_seconds: float = 30.0) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._pool = PersistentMcpClientPool(
            lambda: Client(self.url, timeout=self.timeout_seconds),
            name="control-panel-web",
            size=2,
        )

    async def _call(
        self,
        tool: str,
        arguments: JsonObject | None = None,
    ) -> JsonObject:
        result = await self._pool.call_tool(
            tool,
            arguments or {},
            timeout_seconds=self.timeout_seconds,
        )
        decoded = _decode_call_result(result)
        if decoded is None:
            raise RuntimeError(f"{tool} returned no result")
        return json_object(decoded, context=f"web admin {tool}")

    async def status(self) -> BrowserStatus:
        return BrowserStatus.model_validate(await self._call("browser_status"))

    async def set_viewport(self, page_id: str, width: int, height: int) -> BrowserViewportResult:
        return BrowserViewportResult.model_validate(
            await self._call(
                "browser_set_viewport",
                {"page_id": page_id, "width": width, "height": height},
            )
        )

    async def set_theme(self, color_scheme: str) -> BrowserStatus:
        return BrowserStatus.model_validate(
            await self._call("browser_set_theme", {"color_scheme": color_scheme})
        )

    async def set_tab_policy(
        self, *, max_tabs: int, idle_close_enabled: bool, idle_timeout_seconds: int
    ) -> BrowserStatus:
        return BrowserStatus.model_validate(
            await self._call(
                "browser_set_tab_policy",
                {
                    "max_tabs": max_tabs,
                    "idle_close_enabled": idle_close_enabled,
                    "idle_timeout_seconds": idle_timeout_seconds,
                },
            )
        )

    async def debug_target(self, page_id: str) -> BrowserDebugTarget:
        return BrowserDebugTarget.model_validate(
            await self._call("browser_debug_target", {"page_id": page_id})
        )

    async def hard_stop(self) -> BrowserStopResult:
        return BrowserStopResult.model_validate(await self._call("browser_hard_stop"))

    async def restart(self) -> BrowserStatus:
        return BrowserStatus.model_validate(await self._call("browser_restart"))

    async def external_status(self) -> ExternalBrowserStatus:
        return ExternalBrowserStatus.model_validate(await self._call("browser_external_status"))

    async def external_connect(self) -> ExternalBrowserAction:
        return ExternalBrowserAction.model_validate(await self._call("browser_external_connect"))

    async def external_disconnect(self) -> ExternalBrowserAction:
        return ExternalBrowserAction.model_validate(await self._call("browser_external_disconnect"))

    async def external_reset(self) -> ExternalBrowserAction:
        return ExternalBrowserAction.model_validate(await self._call("browser_external_reset"))
