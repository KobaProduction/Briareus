"""Structural account boundary shared by leased and administrative adapters."""

from typing import Protocol

from service_runtime.account_contracts import AccountList, ResolvedAccount


class AccountAccess(Protocol):
    def list_accounts(self, *, provider: str | None = None) -> AccountList: ...

    def resolve_account(self, selector: str, *, provider: str) -> ResolvedAccount: ...
