"""Web-owned shared browser MCP methods; local entrypoints retain registration."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from mcp.types import CallToolResult, TextContent
from pydantic import BaseModel

from web_runtime.browser_models import (
    BrowserDiagnostics,
    BrowserPages,
    BrowserStatus,
    ClosedPage,
    DebugTarget,
    PageSummary,
)


def present_browser(result: BaseModel) -> CallToolResult:
    payload = result.model_dump(mode="json", by_alias=True, exclude_unset=True)
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, allow_nan=False))
        ],
        structured_content=payload,
    )


class _BrowserToolRuntime(Protocol):
    async def diagnostics(self) -> BrowserDiagnostics: ...

    async def status(self) -> BrowserStatus: ...

    async def restart(self) -> BrowserStatus: ...

    async def pages(self) -> BrowserPages: ...

    async def open(self, url: str, page_id: str = "") -> PageSummary: ...

    async def set_color_scheme(self, color_scheme: str) -> BrowserStatus: ...

    async def debug_target(self, page_id: str) -> DebugTarget: ...

    async def set_viewport(self, page_id: str, width: int, height: int) -> PageSummary: ...

    async def set_page_label(self, page_id: str, label: str) -> PageSummary: ...

    async def snapshot(
        self, page_id: str, *, max_text_chars: int | None = None, max_elements: int | None = None
    ) -> PageSummary: ...

    async def click(self, page_id: str, ref: str) -> PageSummary: ...

    async def fill(
        self, page_id: str, ref: str, value: str, *, press_enter: bool
    ) -> PageSummary: ...

    async def press(self, page_id: str, ref: str, key: str) -> PageSummary: ...

    async def select_option(self, page_id: str, ref: str, value: str) -> PageSummary: ...

    async def upload(self, page_id: str, ref: str, workspace_path: str) -> PageSummary: ...

    async def wait(self, page_id: str, *, state: str, timeout_seconds: float) -> PageSummary: ...

    async def back(self, page_id: str) -> PageSummary: ...

    async def reload(self, page_id: str) -> PageSummary: ...

    async def close_page(self, page_id: str) -> ClosedPage: ...


class _BrowserToolMethods[BrowserT: _BrowserToolRuntime]:
    browser: BrowserT
    _present_browser: Callable[[BaseModel], CallToolResult]

    async def browser_diagnostics(self) -> CallToolResult:
        """Run a bounded Chromium executable/headless probe and return stderr/stdout tails."""
        return self._present_browser(await self.browser.diagnostics())

    async def browser_status(self) -> CallToolResult:
        """Start the persistent Chromium profile if needed and report browser/page status."""
        return self._present_browser(await self.browser.status())

    async def browser_restart(self) -> CallToolResult:
        """Restart Chromium while preserving profile, cookies, storage and dev extensions."""
        return self._present_browser(await self.browser.restart())

    async def browser_pages(self) -> CallToolResult:
        """List open browser pages/tabs in the persistent browser context."""
        return self._present_browser(await self.browser.pages())

    async def browser_open(self, url: str, page_id: str = "") -> CallToolResult:
        """Open a URL in a new page, or navigate an existing page_id."""
        return self._present_browser(await self.browser.open(url, page_id))

    async def browser_set_theme(self, color_scheme: str) -> CallToolResult:
        """Set persistent browser color scheme: dark, light, or system."""
        return self._present_browser(await self.browser.set_color_scheme(color_scheme))

    async def browser_debug_target(self, page_id: str) -> CallToolResult:
        """Resolve the CDP target for one application page without exposing the raw debug port."""
        return self._present_browser(await self.browser.debug_target(page_id))

    async def browser_set_viewport(self, page_id: str, width: int, height: int) -> CallToolResult:
        """Set one browser page viewport and return the effective measured viewport."""
        return self._present_browser(await self.browser.set_viewport(page_id, width, height))

    async def browser_set_page_label(self, page_id: str, label: str) -> CallToolResult:
        """Assign or clear a short human-readable label for one browser tab."""
        return self._present_browser(await self.browser.set_page_label(page_id, label))

    async def browser_snapshot(
        self, page_id: str, max_text_chars: int | None = None, max_elements: int | None = None
    ) -> CallToolResult:
        """Return bounded page text plus visible interactive elements with short refs.

        Refs are intentionally ephemeral. Take a fresh snapshot after meaningful DOM
        changes before clicking/filling again.
        """
        return self._present_browser(
            await self.browser.snapshot(
                page_id, max_text_chars=max_text_chars, max_elements=max_elements
            )
        )

    async def browser_click(self, page_id: str, ref: str) -> CallToolResult:
        """Click one interactive element ref from the latest browser_snapshot."""
        return self._present_browser(await self.browser.click(page_id, ref))

    async def browser_fill(
        self, page_id: str, ref: str, value: str, press_enter: bool = False
    ) -> CallToolResult:
        """Replace the value of one input/textarea ref; optionally press Enter."""
        return self._present_browser(
            await self.browser.fill(page_id, ref, value, press_enter=press_enter)
        )

    async def browser_press(self, page_id: str, ref: str, key: str) -> CallToolResult:
        """Press a Playwright key chord on one element ref (for example Enter or Control+A)."""
        return self._present_browser(await self.browser.press(page_id, ref, key))

    async def browser_select_option(self, page_id: str, ref: str, value: str) -> CallToolResult:
        """Select one HTML select option by value."""
        return self._present_browser(await self.browser.select_option(page_id, ref, value))

    async def browser_upload(self, page_id: str, ref: str, workspace_path: str) -> CallToolResult:
        """Attach one existing shared-workspace file to a file-input element ref."""
        return self._present_browser(await self.browser.upload(page_id, ref, workspace_path))

    async def browser_wait(
        self, page_id: str, state: str = "networkidle", timeout_seconds: float = 30
    ) -> CallToolResult:
        """Wait for a browser page load state without repeatedly polling snapshots."""
        return self._present_browser(
            await self.browser.wait(page_id, state=state, timeout_seconds=timeout_seconds)
        )

    async def browser_back(self, page_id: str) -> CallToolResult:
        """Navigate one browser page backward."""
        return self._present_browser(await self.browser.back(page_id))

    async def browser_reload(self, page_id: str) -> CallToolResult:
        """Reload one browser page."""
        return self._present_browser(await self.browser.reload(page_id))

    async def browser_close_page(self, page_id: str) -> CallToolResult:
        """Close one browser page/tab; the persistent browser profile remains intact."""
        return self._present_browser(await self.browser.close_page(page_id))
