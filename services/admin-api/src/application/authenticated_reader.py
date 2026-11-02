"""Synchronize the reserved GitHub token account without replacing an App identity."""

from dataclasses import replace
from typing import Protocol

from domain.accounts import Account, AuthType, Provider

from application._accounts_binding import _AccountsBinding


class ReaderAuthenticationConflict(Exception):
    """The reserved reader alias already belongs to a different authentication kind."""


class ReaderAccounts(Protocol):
    async def get(
        self, selector: str, *, provider: Provider, enabled_only: bool = True
    ) -> Account: ...

    async def create(self, account: Account, *, credential: str) -> Account: ...
    async def update(self, account: Account) -> Account: ...
    async def set_credential(
        self, account_id: str, credential: str, *, provider: Provider
    ) -> None: ...


class SyncAuthenticatedReader(_AccountsBinding[ReaderAccounts]):
    async def execute(self, token: str) -> Account:
        try:
            account = await self._accounts.get(
                "authenticated", provider=Provider.GITHUB, enabled_only=False
            )
        except KeyError:
            return await self._accounts.create(
                Account(
                    alias="authenticated",
                    provider=Provider.GITHUB,
                    auth_type=AuthType.GITHUB_TOKEN,
                    enabled=True,
                ),
                credential=token,
            )
        if account.auth_type is not AuthType.GITHUB_TOKEN:
            raise ReaderAuthenticationConflict(
                "authenticated GitHub reader exists with incompatible auth_type"
            )
        if not account.enabled:
            account = await self._accounts.update(replace(account, enabled=True))
        await self._accounts.set_credential(account.id, token, provider=Provider.GITHUB)
        return account
