"""Private references for identical provider lifecycle and browser store adapters."""

from typing import TYPE_CHECKING

from service_runtime._async_http_lifecycle import _OwnedClient as _OwnedClient
from service_runtime._reference_bindings import _ClientBinding as _ClientBinding

if TYPE_CHECKING:
    from control_panel_api._rauthy_native_init import PinnedNativeRauthyInit
    from control_panel_api.domain.platform_authority import PanelOidcSession
    from control_panel_api.infrastructure.browser_sessions import ValkeyBrowserSessions


class _ProviderBinding[ProviderT]:
    def __init__(self, provider: ProviderT) -> None:
        self._provider = provider


class _BrowserSessionRead:
    _sessions: "ValkeyBrowserSessions"

    async def _session(self, ticket: str) -> "PanelOidcSession | None":
        return await self._sessions.get_session(ticket)


class _BrowserSessionDelete:
    _sessions: "ValkeyBrowserSessions"

    async def delete(self, ticket: str) -> None:
        await self._sessions.delete_session(ticket)


class _NativePow:
    _native: "PinnedNativeRauthyInit"

    async def issue_pow(self) -> str:
        return await self._native.issue_pow()
