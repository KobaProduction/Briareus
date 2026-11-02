"""One owner store implements the focused browser persistence roles directly."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import SecretStr
from valkey.asyncio import Valkey

from control_panel_api.infrastructure.browser_native_transactions import ValkeyNativeTransactions
from control_panel_api.infrastructure.browser_renewal import renew_browser_session
from control_panel_api.infrastructure.browser_sessions import ValkeyBrowserSessions
from control_panel_api.infrastructure.browser_storage import BrowserStorageContext
from control_panel_api.infrastructure.browser_transactions import ValkeyOidcTransactions

if TYPE_CHECKING:
    from control_panel_api._oidc import RauthyOidcAdapter


class OidcBrowserSessionStore(
    ValkeyBrowserSessions, ValkeyOidcTransactions, ValkeyNativeTransactions
):
    def __init__(self, *, password: SecretStr, client: Valkey | None = None) -> None:
        self.storage = BrowserStorageContext(password=password, client=client)
        self._storage = self.storage

    async def close(self) -> None:
        await self.storage.close()

    @property
    def _client(self) -> Valkey:
        return self.storage.client

    @_client.setter
    def _client(self, client: Valkey) -> None:
        self.storage.client = client

    _key = staticmethod(BrowserStorageContext.key)

    async def renew_session(self, ticket: str, provider: RauthyOidcAdapter) -> int | None:
        return await renew_browser_session(self.storage, ticket, provider)
