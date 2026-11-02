"""Typed projections of Resources-owned connection JSONB, with explicit format version."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from projects.domain.connection_settings import ConnectionSettings
from projects.infrastructure.connection_policy_codec import policy_form, policy_record
from runtime_peer.connection_contracts import GitLabPolicyForm, GitPolicyForm


class StoredConnectionVersion(BaseModel):
    # Earlier rows have the same v1 shape without a marker. One codec reads both;
    # all new writes include the marker and unknown versions fail closed.
    model_config = ConfigDict(extra="ignore", strict=True)
    schema_version: Literal[1] = 1


class StoredAccountEndpoint(StoredConnectionVersion):
    base_url: str = ""
    external_id: str | None = None
    ca_cert_pem: str | None = None


class StoredConnectionSettings(StoredAccountEndpoint):
    name: str = ""
    display_name: str | None = None
    provider: str = ""
    auth_type: str = ""
    git_policy: GitPolicyForm | GitLabPolicyForm | None = None

    def record(self, *, provider: str, auth_type: str, alias: str) -> ConnectionSettings:
        return ConnectionSettings(
            name=self.display_name or alias,
            provider=provider,
            auth_type=auth_type,
            base_url=self.base_url,
            ca_cert_pem=self.ca_cert_pem or "",
            external_id=self.external_id,
            git_policy=None if self.git_policy is None else policy_record(self.git_policy),
        )

    @classmethod
    def from_record(cls, value: ConnectionSettings) -> StoredConnectionSettings:
        return cls(
            schema_version=1,
            name=value.name,
            display_name=value.name,
            provider=value.provider,
            auth_type=value.auth_type,
            base_url=value.base_url,
            ca_cert_pem=value.ca_cert_pem,
            external_id=value.external_id,
            git_policy=None if value.git_policy is None else policy_form(value.git_policy),
        )


class StoredGitHubPolicy(StoredConnectionVersion):
    git_policy: GitPolicyForm = Field(default_factory=GitPolicyForm)


class StoredGitLabPolicy(StoredConnectionVersion):
    git_policy: GitLabPolicyForm = Field(default_factory=GitLabPolicyForm)
