from __future__ import annotations

from typing import Literal

from pydantic import Field

from .events import InvocationEvent as InvocationEvent
from .models import StrictModel


class AccountPublic(StrictModel):
    id: str
    alias: str
    provider: Literal["github", "gitlab", "signoz", "coolify"]
    auth_type: str
    base_url: str
    external_id: str | None = None
    verify_tls: bool = True
    ca_cert_pem: str | None = None
    enabled: bool = True
    created_at: str
    updated_at: str


class AccountConnectionSummary(AccountPublic):
    credential_configured: bool


class ResolvedAccount(AccountPublic):
    credential: str = Field(min_length=1)

    @classmethod
    def from_public(cls, account: AccountPublic, credential: str) -> ResolvedAccount:
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
            credential=credential,
        )


class GitHubAuthenticatedReaderSync(StrictModel):
    token: str = Field(min_length=1)
    login: str = Field(min_length=1, max_length=128)


class AccountList(StrictModel):
    accounts: list[AccountPublic]
    count: int = Field(ge=0)


class SourceInventoryView(StrictModel):
    sources: list[AccountPublic]
    count: int


class InvocationEventBatch(StrictModel):
    events: list[InvocationEvent] = Field(min_length=1, max_length=128)


class AuthenticatedReaderView(AccountPublic):
    login: str
    synced: Literal[True] = True

    @classmethod
    def from_public(cls, account: AccountPublic, login: str) -> AuthenticatedReaderView:
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
            login=login,
            synced=True,
        )
