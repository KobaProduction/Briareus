"""Decode the account adapter's public contract without copying any credential."""

from common.account_access import AccountAccess

from common.account_contracts import AccountPublic
from modules.observability.domain.sources import ProviderName, PublicSource


class AccountSourceCatalog:
    def __init__(self, accounts: AccountAccess) -> None:
        self._accounts = accounts

    def accounts(self, provider: ProviderName) -> tuple[PublicSource, ...]:
        return tuple(
            _public_source(item, provider)
            for item in self._accounts.list_accounts(provider=provider).accounts
        )


def _public_source(item: AccountPublic, provider: ProviderName) -> PublicSource:
    if item.provider != provider:
        raise ValueError("Infrastructure source provider does not match current query")
    return PublicSource(
        item.id,
        item.alias,
        provider,
        item.auth_type,
        item.base_url,
        item.external_id,
        item.verify_tls,
        item.ca_cert_pem,
        item.enabled,
        item.created_at,
        item.updated_at,
    )
