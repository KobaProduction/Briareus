from __future__ import annotations

from typing import Literal

from pydantic import Field, PrivateAttr, TypeAdapter, field_validator, model_validator

from service_runtime.account_contracts import ResolvedAccount
from service_runtime.models import StrictModel

from .domain.mutations import CommitAction, CommitEdit
from .project_views import PublicGitLabProfile


class GitLabProfile(StrictModel):
    _token: str = PrivateAttr(default="")

    account_id: str = Field(min_length=1)
    alias: str = Field(min_length=1)
    base_url: str = Field(min_length=1)
    auth_type: Literal["private_token", "bearer", "job_token"]
    verify_tls: bool = True
    ca_cert_pem: str = ""

    @classmethod
    def from_account(cls, account: ResolvedAccount) -> GitLabProfile:
        profile = cls(
            account_id=account.id,
            alias=account.alias,
            base_url=account.base_url,
            auth_type=TypeAdapter(Literal["private_token", "bearer", "job_token"]).validate_python(
                account.auth_type
            ),
            verify_tls=account.verify_tls,
            ca_cert_pem=account.ca_cert_pem or "",
        )
        profile.bind_token(account.credential)
        return profile

    @field_validator("base_url")
    @classmethod
    def strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")

    @property
    def profile_id(self) -> str:
        return self.account_id

    @property
    def api_url(self) -> str:
        return self.base_url + "/api/v4"

    def bind_token(self, token: str) -> None:
        value = token.strip()
        if not value:
            raise ValueError("GitLab credential is empty")
        self._token = value

    def token(self) -> str:
        if not self._token:
            raise RuntimeError("GitLab credential is not bound")
        return self._token

    def public(self) -> PublicGitLabProfile:
        return PublicGitLabProfile(
            account_id=self.account_id,
            alias=self.alias,
            base_url=self.base_url,
            api_url=self.api_url,
            auth_type=self.auth_type,
            credential_configured=bool(self._token),
            verify_tls=self.verify_tls,
            ca_cert_pem_configured=bool(self.ca_cert_pem),
        )


class GitLabCommitAction(StrictModel):
    action: CommitAction
    file_path: str = Field(min_length=1)
    content: str | None = None
    previous_path: str | None = None
    encoding: Literal["text", "base64"] | None = None
    execute_filemode: bool | None = None
    last_commit_id: str | None = None

    @model_validator(mode="after")
    def validate_action(self) -> GitLabCommitAction:
        CommitEdit(self.action, self.file_path, self.content, self.previous_path).require_complete()
        return self
