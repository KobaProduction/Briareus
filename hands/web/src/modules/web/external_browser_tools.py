"""MCP presentation of the configured external browser lifecycle."""

from dataclasses import dataclass

from fastmcp import FastMCP
from mcp.types import CallToolResult

from common.runtime_annotations import READ_EXTERNAL, WRITE_EXTERNAL

from .external_browser_models import present_external_status
from .external_browser_proxy import ExternalBrowserProxyRuntime


@dataclass(frozen=True)
class ExternalBrowserTools[AppState]:
    external: ExternalBrowserProxyRuntime[AppState]

    async def browser_external_status(self) -> CallToolResult:
        """Report configuration and live state for the external Playwright MCP bridge."""
        return present_external_status(await self.external.status())

    async def browser_external_connect(self) -> CallToolResult:
        """Connect the configured external Playwright MCP server and keep the session alive."""
        return present_external_status(await self.external.connect())

    async def browser_external_disconnect(self) -> CallToolResult:
        """Close the persistent external Playwright MCP session without stopping Chrome."""
        return present_external_status(await self.external.disconnect())

    async def browser_external_reset(self) -> CallToolResult:
        """Reset the external MCP session and reconnect using placement configuration."""
        return present_external_status(await self.external.reset())


def register_external_tools[AppState](
    mcp: FastMCP[AppState],
    external: ExternalBrowserProxyRuntime[AppState],
) -> None:
    adapter = ExternalBrowserTools(external)
    mcp.tool(
        name="external_status", title="Connected external browser status", annotations=READ_EXTERNAL
    )(adapter.browser_external_status)
    mcp.tool(name="external_connect", title="Connect external browser", annotations=WRITE_EXTERNAL)(
        adapter.browser_external_connect
    )
    mcp.tool(
        name="external_disconnect", title="Disconnect external browser", annotations=WRITE_EXTERNAL
    )(adapter.browser_external_disconnect)
    mcp.tool(name="external_reset", title="Reset external browser", annotations=WRITE_EXTERNAL)(
        adapter.browser_external_reset
    )
