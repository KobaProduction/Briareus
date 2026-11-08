from typing import Protocol

from control_panel_api.domain.admin_data.browser import (
    BrowserDebugTarget,
    BrowserStatus,
    BrowserStopResult,
    BrowserViewportResult,
    ExternalBrowserAction,
    ExternalBrowserStatus,
)


class BrowserAdminPort(Protocol):
    async def status(self) -> BrowserStatus: ...

    async def set_viewport(
        self, page_id: str, width: int, height: int
    ) -> BrowserViewportResult: ...

    async def set_theme(self, color_scheme: str) -> BrowserStatus: ...

    async def set_tab_policy(
        self, *, max_tabs: int, idle_close_enabled: bool, idle_timeout_seconds: int
    ) -> BrowserStatus: ...

    async def debug_target(self, page_id: str) -> BrowserDebugTarget: ...

    async def hard_stop(self) -> BrowserStopResult: ...

    async def restart(self) -> BrowserStatus: ...

    async def external_status(self) -> ExternalBrowserStatus: ...

    async def external_connect(self) -> ExternalBrowserAction: ...

    async def external_disconnect(self) -> ExternalBrowserAction: ...

    async def external_reset(self) -> ExternalBrowserAction: ...
