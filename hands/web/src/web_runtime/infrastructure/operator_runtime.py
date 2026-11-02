"""Exact operator-facing browser methods; each target retains access enforcement."""

from __future__ import annotations

from typing import Protocol

from playwright.async_api import CDPSession, Page

from web_runtime.browser_models import (
    AgentAccessStatus,
    CleanBrowserResult,
    ClosedPage,
    DeveloperAccessReceipt,
    OperatorLease,
    OperatorState,
    PageSummary,
)


class OperatorBrowserRuntime(Protocol):
    @property
    def viewport_width(self) -> int: ...

    @property
    def viewport_height(self) -> int: ...

    async def operator_set_page_label(
        self, owner_token: str, page_id: str, label: str
    ) -> PageSummary: ...

    async def operator_set_page_agent_access(
        self, owner_token: str, page_id: str, allowed: bool
    ) -> PageSummary: ...

    async def operator_set_agent_access(
        self, owner_token: str, allowed: bool
    ) -> AgentAccessStatus: ...

    async def operator_set_developer_access(
        self, owner_token: str, allowed: bool
    ) -> DeveloperAccessReceipt: ...

    async def operator_acquire(self) -> OperatorLease: ...

    async def operator_release(self, owner_token: str) -> None: ...

    async def operator_state(self, owner_token: str) -> OperatorState: ...

    async def operator_select_page(self, owner_token: str, page_id: str) -> None: ...

    async def operator_cdp_session(
        self, owner_token: str, page_id: str
    ) -> tuple[Page, CDPSession]: ...

    async def operator_new_page(self, owner_token: str, url: str = "") -> PageSummary: ...

    async def operator_navigate(self, owner_token: str, page_id: str, url: str) -> PageSummary: ...

    async def operator_clean_app(self, owner_token: str, page_id: str) -> PageSummary: ...

    async def operator_clean_browser(self, owner_token: str) -> CleanBrowserResult: ...

    async def operator_back(self, owner_token: str, page_id: str) -> PageSummary: ...

    async def operator_reload(self, owner_token: str, page_id: str) -> PageSummary: ...

    async def operator_reopen_closed_page(self, owner_token: str) -> PageSummary: ...

    async def operator_close_page(self, owner_token: str, page_id: str) -> ClosedPage: ...

    async def operator_mouse(
        self,
        owner_token: str,
        page_id: str,
        *,
        event_type: str,
        x: float,
        y: float,
        button: str,
        click_count: int,
        delta_x: float,
        delta_y: float,
    ) -> None: ...

    async def operator_key(self, owner_token: str, page_id: str, key: str) -> None: ...

    async def operator_text(self, owner_token: str, page_id: str, text: str) -> None: ...
