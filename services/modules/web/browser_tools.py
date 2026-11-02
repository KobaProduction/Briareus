from __future__ import annotations

from dataclasses import dataclass

from fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations

from web_runtime.presentation.browser_tools import _BrowserToolMethods

from .browser import BrowserManager
from .transfer_presenter import present_browser, present_browser_transfer


@dataclass(frozen=True)
class BrowserToolAdapter(_BrowserToolMethods["BrowserManager"]):
    browser: BrowserManager
    _present_browser = staticmethod(present_browser)

    async def browser_download(
        self,
        page_id: str,
        ref: str,
        workspace_path: str,
        overwrite: bool = False,
    ) -> CallToolResult:
        """Click an element expected to download a file and save it into /workspace."""
        result = await self.browser.download(
            page_id,
            ref,
            workspace_path,
            overwrite=overwrite,
        )
        return present_browser_transfer(result)

    async def browser_screenshot(
        self,
        page_id: str,
        workspace_path: str,
        full_page: bool = True,
        overwrite: bool = False,
    ) -> CallToolResult:
        """Capture a PNG screenshot directly into the shared workspace."""
        result = await self.browser.screenshot(
            page_id,
            workspace_path,
            full_page=full_page,
            overwrite=overwrite,
        )
        return present_browser_transfer(result)


def register_browser_tools[AppState](
    mcp: FastMCP[AppState],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    *,
    browser: BrowserManager,
) -> None:
    adapter = BrowserToolAdapter(browser)
    mcp.tool(title="Browser diagnostics", annotations=read_annotations)(adapter.browser_diagnostics)
    mcp.tool(title="Browser status", annotations=read_annotations)(adapter.browser_status)
    mcp.tool(title="Browser restart", annotations=write_annotations)(adapter.browser_restart)
    mcp.tool(title="Browser pages", annotations=read_annotations)(adapter.browser_pages)
    mcp.tool(title="Browser open", annotations=write_annotations)(adapter.browser_open)
    mcp.tool(title="Browser set theme", annotations=write_annotations)(adapter.browser_set_theme)
    mcp.tool(title="Browser remote debug target", annotations=read_annotations)(
        adapter.browser_debug_target
    )
    mcp.tool(title="Browser set viewport", annotations=write_annotations)(
        adapter.browser_set_viewport
    )
    mcp.tool(title="Browser set page label", annotations=write_annotations)(
        adapter.browser_set_page_label
    )
    mcp.tool(title="Browser snapshot", annotations=read_annotations)(adapter.browser_snapshot)
    mcp.tool(title="Browser click", annotations=write_annotations)(adapter.browser_click)
    mcp.tool(title="Browser fill", annotations=write_annotations)(adapter.browser_fill)
    mcp.tool(title="Browser press key", annotations=write_annotations)(adapter.browser_press)
    mcp.tool(title="Browser select option", annotations=write_annotations)(
        adapter.browser_select_option
    )
    mcp.tool(title="Browser upload", annotations=write_annotations)(adapter.browser_upload)
    mcp.tool(title="Browser download", annotations=write_annotations)(adapter.browser_download)
    mcp.tool(title="Browser screenshot", annotations=write_annotations)(adapter.browser_screenshot)
    mcp.tool(title="Browser wait", annotations=read_annotations)(adapter.browser_wait)
    mcp.tool(title="Browser back", annotations=write_annotations)(adapter.browser_back)
    mcp.tool(title="Browser reload", annotations=write_annotations)(adapter.browser_reload)
    mcp.tool(title="Browser close page", annotations=write_annotations)(adapter.browser_close_page)
