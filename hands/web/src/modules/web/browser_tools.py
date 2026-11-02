from __future__ import annotations

import logging
from dataclasses import dataclass

from fastmcp import FastMCP
from mcp.types import CallToolResult, ToolAnnotations

from runtime_peer.browser_arguments import BrowserInput
from runtime_peer.browser_receipts import BrowserInteractionReceipt
from web_runtime.application.browser_input import ApplyBrowserInput
from web_runtime.infrastructure.operator_browser import BrowserOperator
from web_runtime.presentation.browser_input import input_command
from web_runtime.presentation.browser_tools import _BrowserToolMethods

from .browser import BrowserManager
from .transfer_presenter import present_browser, present_browser_transfer

LOG = logging.getLogger(__name__)


@dataclass(frozen=True)
class BrowserToolAdapter(_BrowserToolMethods["BrowserManager"]):
    browser: BrowserManager
    _present_browser = staticmethod(present_browser)

    async def browser_reopen_closed_page(
        self,
    ) -> CallToolResult:
        """Restore the last closed tab in this browser session, respecting its tab limit."""
        return present_browser(await self.browser.reopen_closed_page())

    async def browser_settings(self, section: str) -> CallToolResult:
        """Open Chromium settings or extensions in a new tab; section=settings|extensions.

        This never opens DevTools or changes agent developer-access permissions.
        """
        return present_browser(await self.browser.open_settings(section))

    async def browser_input(self, page_id: str, events: list[BrowserInput]) -> CallToolResult:
        """Apply human pointer/keyboard input to one page and return its updated view."""
        LOG.debug("Human browser input: applying commands")
        await ApplyBrowserInput(BrowserOperator(self.browser)).execute(
            tuple(input_command(page_id, event) for event in events)
        )
        LOG.debug("Human browser input: reading inventory")
        inventory = await self.browser.pages()
        LOG.debug("Human browser input: reading snapshot")
        snapshot = await self.browser.snapshot(page_id)
        LOG.debug("Human browser input: reading preview")
        preview = await self.browser.preview(page_id)
        LOG.debug("Human browser input: completed")
        return present_browser(
            BrowserInteractionReceipt(inventory=inventory, snapshot=snapshot, preview=preview)
        )

    async def browser_download(
        self,
        page_id: str,
        ref: str,
        workspace_path: str,
        overwrite: bool = False,
    ) -> CallToolResult:
        """Click an element expected to download a file and save it into /workspace."""
        return present_browser_transfer(
            await self.browser.download(
                page_id,
                ref,
                workspace_path,
                overwrite=overwrite,
            )
        )

    async def browser_preview(self, page_id: str) -> CallToolResult:
        """Read a bounded PNG viewport preview as base64 without writing project files."""
        return present_browser(await self.browser.preview(page_id))

    async def browser_screenshot(
        self,
        page_id: str,
        workspace_path: str,
        full_page: bool = True,
        overwrite: bool = False,
    ) -> CallToolResult:
        """Capture a PNG screenshot directly into the shared workspace."""
        return present_browser_transfer(
            await self.browser.screenshot(
                page_id,
                workspace_path,
                full_page=full_page,
                overwrite=overwrite,
            )
        )

    async def browser_forward(self, page_id: str) -> CallToolResult:
        """Navigate one explicit browser page forward in its history."""
        return present_browser(await self.browser.forward(page_id))


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
    mcp.tool(title="Restore closed browser tab", annotations=write_annotations)(
        adapter.browser_reopen_closed_page
    )
    mcp.tool(title="Browser settings and extensions", annotations=write_annotations)(
        adapter.browser_settings
    )
    mcp.tool(title="Human browser input", annotations=write_annotations)(adapter.browser_input)
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
    mcp.tool(title="Browser viewport preview", annotations=read_annotations)(
        adapter.browser_preview
    )
    mcp.tool(title="Browser screenshot", annotations=write_annotations)(adapter.browser_screenshot)
    mcp.tool(title="Browser wait", annotations=read_annotations)(adapter.browser_wait)
    mcp.tool(title="Browser forward", annotations=write_annotations)(adapter.browser_forward)
    mcp.tool(title="Browser back", annotations=write_annotations)(adapter.browser_back)
    mcp.tool(title="Browser reload", annotations=write_annotations)(adapter.browser_reload)
    mcp.tool(title="Browser close page", annotations=write_annotations)(adapter.browser_close_page)
