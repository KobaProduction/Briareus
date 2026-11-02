"""Map account values to the existing public DTO without exposing credentials."""

from domain.accounts import Account
from domain.web_accounts import utc_timestamp

from common.account_contracts import AccountPublic


def public_account(account: Account) -> AccountPublic:
    return AccountPublic(
        id=account.id,
        alias=account.alias,
        provider=account.provider.value,
        auth_type=account.auth_type.value,
        base_url=account.base_url,
        external_id=account.external_id or None,
        verify_tls=account.verify_tls,
        ca_cert_pem=account.ca_cert_pem or None,
        enabled=account.enabled,
        created_at=utc_timestamp(account.created_at).isoformat(),
        updated_at=utc_timestamp(account.updated_at).isoformat(),
    )
