from __future__ import annotations

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from briareus_playwright.browser import BrowserManager


def register_browser_tools(
    mcp: FastMCP[None],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    *,
    browser: BrowserManager,
) -> None:
    _register_session_tools(mcp, read_annotations, write_annotations, browser=browser)
    _register_page_tools(mcp, read_annotations, write_annotations, browser=browser)
    _register_transfer_navigation_tools(mcp, read_annotations, write_annotations, browser=browser)


def _register_session_tools(
    mcp: FastMCP[None],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    *,
    browser: BrowserManager,
) -> None:
    @mcp.tool(title="Browser diagnostics", annotations=read_annotations)
    async def browser_diagnostics() -> JsonObject:
        """Report the persistent Chromium owner and its CDP connection."""
        return await browser.diagnostics()

    @mcp.tool(title="Browser status", annotations=read_annotations)
    async def browser_status() -> JsonObject:
        """Start the persistent Chromium profile if needed and report browser/page status."""
        return await browser.status()

    @mcp.tool(title="Browser restart", annotations=write_annotations)
    async def browser_restart() -> JsonObject:
        """Restart Chromium while preserving profile, cookies, storage and dev extensions."""
        return await browser.restart()

    @mcp.tool(title="Browser hard stop", annotations=write_annotations)
    async def browser_hard_stop() -> JsonObject:
        """Force-kill the independent Chromium process group without deleting its profile."""
        return await browser.hard_stop()

    @mcp.tool(title="Browser pages", annotations=read_annotations)
    async def browser_pages() -> JsonObject:
        """List open browser pages/tabs in the persistent browser context."""
        return await browser.pages()

    @mcp.tool(title="Browser open", annotations=write_annotations)
    async def browser_open(url: str, page_id: str = "") -> JsonObject:
        """Open a URL in a new page, or navigate an existing page_id."""
        return await browser.open(url, page_id)

    @mcp.tool(title="Browser tab policy", annotations=write_annotations)
    async def browser_set_tab_policy(
        max_tabs: int, idle_close_enabled: bool, idle_timeout_seconds: int
    ) -> JsonObject:
        """Persist tab limit and idle closure (seconds); active work is protected."""
        return await browser.set_tab_policy(max_tabs, idle_close_enabled, idle_timeout_seconds)

    @mcp.tool(title="Browser close all tabs", annotations=write_annotations)
    async def browser_close_all() -> JsonObject:
        """Explicitly close all managed tabs, preserving the browser profile."""
        return await browser.close_all()

    @mcp.tool(title="Browser set theme", annotations=write_annotations)
    async def browser_set_theme(color_scheme: str) -> JsonObject:
        """Set persistent browser color scheme: dark, light, or system."""
        return await browser.set_color_scheme(color_scheme)


def _register_page_tools(
    mcp: FastMCP[None],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    *,
    browser: BrowserManager,
) -> None:
    @mcp.tool(title="Browser remote debug target", annotations=read_annotations)
    async def browser_debug_target(page_id: str) -> JsonObject:
        """Resolve the CDP target for one application page without exposing the raw debug port."""
        return await browser.debug_target(page_id)

    @mcp.tool(title="Browser set viewport", annotations=write_annotations)
    async def browser_set_viewport(page_id: str, width: int, height: int) -> JsonObject:
        """Set one browser page viewport and return the effective measured viewport."""
        return await browser.set_viewport(page_id, width, height)

    @mcp.tool(title="Browser set page label", annotations=write_annotations)
    async def browser_set_page_label(page_id: str, label: str) -> JsonObject:
        """Assign or clear a short human-readable label for one browser tab."""
        return await browser.set_page_label(page_id, label)

    @mcp.tool(title="Browser snapshot", annotations=read_annotations)
    async def browser_snapshot(
        page_id: str,
        max_text_chars: int | None = None,
        max_elements: int | None = None,
    ) -> JsonObject:
        """Return bounded page text plus visible interactive elements with short refs.

        Refs are intentionally ephemeral. Take a fresh snapshot after meaningful DOM
        changes before clicking/filling again.
        """
        return await browser.snapshot(
            page_id,
            max_text_chars=max_text_chars,
            max_elements=max_elements,
        )

    @mcp.tool(title="Browser click", annotations=write_annotations)
    async def browser_click(page_id: str, ref: str) -> JsonObject:
        """Click one interactive element ref from the latest browser_snapshot."""
        return await browser.click(page_id, ref)

    @mcp.tool(title="Browser fill", annotations=write_annotations)
    async def browser_fill(
        page_id: str,
        ref: str,
        value: str,
        press_enter: bool = False,
    ) -> JsonObject:
        """Replace the value of one input/textarea ref; optionally press Enter."""
        return await browser.fill(page_id, ref, value, press_enter=press_enter)

    @mcp.tool(title="Browser press key", annotations=write_annotations)
    async def browser_press(page_id: str, ref: str, key: str) -> JsonObject:
        """Press a Playwright key chord on one element ref (for example Enter or Control+A)."""
        return await browser.press(page_id, ref, key)

    @mcp.tool(title="Browser select option", annotations=write_annotations)
    async def browser_select_option(page_id: str, ref: str, value: str) -> JsonObject:
        """Select one HTML select option by value."""
        return await browser.select_option(page_id, ref, value)


def _register_transfer_navigation_tools(
    mcp: FastMCP[None],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    *,
    browser: BrowserManager,
) -> None:
    @mcp.tool(title="Browser upload", annotations=write_annotations)
    async def browser_upload(page_id: str, ref: str, workspace_path: str) -> JsonObject:
        """Attach one existing shared-workspace file to a file-input element ref."""
        return await browser.upload(page_id, ref, workspace_path)

    @mcp.tool(title="Browser download", annotations=write_annotations)
    async def browser_download(
        page_id: str,
        ref: str,
        workspace_path: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        """Download into Server browser/downloads, or move the saved file to workspace_path."""
        return await browser.download(
            page_id,
            ref,
            workspace_path,
            overwrite=overwrite,
        )

    @mcp.tool(title="Browser screenshot", annotations=write_annotations)
    async def browser_screenshot(
        page_id: str,
        workspace_path: str,
        full_page: bool = True,
        overwrite: bool = False,
    ) -> JsonObject:
        """Capture a PNG screenshot directly into the shared workspace."""
        return await browser.screenshot(
            page_id,
            workspace_path,
            full_page=full_page,
            overwrite=overwrite,
        )

    @mcp.tool(title="Browser wait", annotations=read_annotations)
    async def browser_wait(
        page_id: str,
        state: str = "networkidle",
        timeout_seconds: float = 30,
    ) -> JsonObject:
        """Wait for a browser page load state without repeatedly polling snapshots."""
        return await browser.wait(
            page_id,
            state=state,
            timeout_seconds=timeout_seconds,
        )

    @mcp.tool(title="Browser back", annotations=write_annotations)
    async def browser_back(page_id: str) -> JsonObject:
        """Navigate one browser page backward."""
        return await browser.back(page_id)

    @mcp.tool(title="Browser reload", annotations=write_annotations)
    async def browser_reload(page_id: str) -> JsonObject:
        """Reload one browser page."""
        return await browser.reload(page_id)

    @mcp.tool(title="Browser close page", annotations=write_annotations)
    async def browser_close_page(page_id: str) -> JsonObject:
        """Close one browser page/tab; the persistent browser profile remains intact."""
        return await browser.close_page(page_id)
