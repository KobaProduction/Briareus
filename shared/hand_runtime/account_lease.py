"""Adapt current account custody to provider clients; public views omit credentials."""

from collections.abc import Sequence
from uuid import UUID

from common.account_contracts import AccountList, AccountPublic, ResolvedAccount
from node_protocol.provider_context import ProjectAccount

from .domain.account_lease import AccountIdentity, AccountLease


def _public_account(account: ProjectAccount | AccountPublic) -> AccountPublic:
    return AccountPublic.model_validate(
        {
            "id": str(account.id),
            "alias": account.alias,
            "provider": account.provider,
            "auth_type": account.auth_type,
            "base_url": account.base_url,
            "external_id": account.external_id,
            "verify_tls": account.verify_tls,
            "ca_cert_pem": account.ca_cert_pem,
            "enabled": account.enabled,
            "created_at": account.created_at,
            "updated_at": account.updated_at,
        }
    )


class InvocationAccounts:
    def __init__(self, accounts: Sequence[ProjectAccount]) -> None:
        self._accounts: tuple[AccountPublic | ResolvedAccount, ...] = ()
        self._lease = AccountLease(())
        self.bind(accounts)

    def bind(self, accounts: Sequence[ProjectAccount]) -> None:
        if len(accounts) > 64:
            raise ValueError("Bounded current account lease required")
        parsed = tuple(parse_account(item) for item in accounts)
        lease = AccountLease(
            tuple(
                AccountIdentity(item.provider, UUID(item.id), item.alias, item.enabled)
                for item in parsed
            )
        )
        self._accounts, self._lease = parsed, lease

    def list_accounts(self, *, provider: str | None = None) -> AccountList:
        rows = [
            _public_account(item)
            for item in self._accounts
            if provider is None or item.provider == provider
        ]
        return AccountList(accounts=rows, count=len(rows))

    def resolve_account(self, selector: object, *, provider: str) -> ResolvedAccount:
        account = self._accounts[self._lease.resolve(selector, provider)]
        if not isinstance(account, ResolvedAccount):
            raise ValueError("Current private credential lease required for provider effect")
        return account

    def clear(self) -> None:
        self._accounts = ()
        self._lease = AccountLease(())


def parse_account(value: ProjectAccount) -> AccountPublic | ResolvedAccount:
    public = _public_account(value)
    if value.credential is None:
        if "credential" in value.model_fields_set:
            raise ValueError("Current private credential lease required")
        return public
    return ResolvedAccount.from_public(public, value.credential)
