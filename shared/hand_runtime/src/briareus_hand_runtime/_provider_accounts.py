"""Provider-scoped account lookup and revision-aware client reuse for MCP services."""

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from briareus_account_contracts import AccountPublic, ResolvedAccount
from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_json_values import StrictModel

type AccountProvider = Literal["github", "gitlab", "signoz", "coolify"]


class ProviderSources(StrictModel):
    sources: list[AccountPublic]
    count: int


@dataclass(frozen=True)
class _CachedClient[T]:
    revision: str
    client: T


class ProviderClientCache[T]:
    def __init__(
        self,
        management: ControlPanelClient,
        provider: AccountProvider,
        factory: Callable[[ResolvedAccount], T],
    ) -> None:
        self.management = management
        self.provider = provider
        self.factory = factory
        self._lock = threading.Lock()
        self._clients: dict[str, _CachedClient[T]] = {}

    def sources(self) -> ProviderSources:
        accounts = self.management.list_accounts(provider=self.provider)
        return ProviderSources(sources=accounts.accounts, count=accounts.count)

    def client(self, account_id: str) -> T:
        account = self.management.resolve_account(account_id, provider=self.provider)
        with self._lock:
            cached = self._clients.get(account.id)
            if cached is not None and cached.revision == account.updated_at:
                return cached.client
            client = self.factory(account)
            self._clients[account.id] = _CachedClient(account.updated_at, client)
            return client
