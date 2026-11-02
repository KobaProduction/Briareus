"""Infrastructure account-bound clients with per-context cache ownership."""

from __future__ import annotations

import threading
from typing import Protocol

from service_runtime.account_contracts import AccountList, ResolvedAccount

from .providers.coolify.client import CoolifyClient
from .providers.signoz.client import SigNozClient


class AccountAccess(Protocol):
    def list_accounts(self, *, provider: str | None = None) -> AccountList: ...

    def resolve_account(self, selector: str, *, provider: str) -> ResolvedAccount: ...


class ObservabilityAccountClients[AccountSourceT: AccountAccess]:
    def __init__(self, admin_api: AccountSourceT) -> None:
        self.admin_api = admin_api
        self._lock = threading.Lock()
        self._signoz: dict[str, tuple[str, SigNozClient]] = {}
        self._coolify: dict[str, tuple[str, CoolifyClient]] = {}

    def signoz(self, account_id: str) -> SigNozClient:
        account = self.admin_api.resolve_account(account_id, provider="signoz")
        with self._lock:
            cached = self._signoz.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = SigNozClient(account)
            self._signoz[account.id] = (account.updated_at, client)
            return client

    def coolify(self, account_id: str) -> CoolifyClient:
        account = self.admin_api.resolve_account(account_id, provider="coolify")
        with self._lock:
            cached = self._coolify.get(account.id)
            if cached is not None and cached[0] == account.updated_at:
                return cached[1]
            client = CoolifyClient(account)
            self._coolify[account.id] = (account.updated_at, client)
            return client
