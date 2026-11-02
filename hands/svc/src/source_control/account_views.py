"""Credential-free source account catalog projections, never access grants."""

from typing import Self

from service_runtime.account_contracts import AccountPublic


class SourceAccountView(AccountPublic):
    potential_capabilities: list[str]
    permission_scope: str
    preferred_selector: str
    selector_stability: str = "stable_alias"

    @classmethod
    def from_account(
        cls,
        account: AccountPublic,
        *,
        potential_capabilities: list[str],
        permission_scope: str,
    ) -> Self:
        return cls(
            id=account.id,
            alias=account.alias,
            provider=account.provider,
            auth_type=account.auth_type,
            base_url=account.base_url,
            external_id=account.external_id,
            verify_tls=account.verify_tls,
            ca_cert_pem=account.ca_cert_pem,
            enabled=account.enabled,
            created_at=account.created_at,
            updated_at=account.updated_at,
            potential_capabilities=potential_capabilities,
            permission_scope=permission_scope,
            preferred_selector=account.alias,
        )
