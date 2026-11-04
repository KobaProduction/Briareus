from __future__ import annotations

from typing import Literal

from briareus_json_values import JsonObject, StrictModel
from pydantic import Field


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


class ResolvedAccount(AccountPublic):
    credential: str = Field(min_length=1)


class GitHubAuthenticatedReaderSync(StrictModel):
    token: str = Field(min_length=1)
    login: str = Field(min_length=1, max_length=128)


class AccountList(StrictModel):
    accounts: list[AccountPublic]
    count: int = Field(ge=0)

    def to_json(self) -> JsonObject:
        return self.model_dump(mode="json")
