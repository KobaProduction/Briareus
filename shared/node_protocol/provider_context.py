"""Project-scoped provider custody contract shared by Core and execution adapters."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StrictInt


class ProjectAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    id: UUID
    alias: str
    provider: str
    auth_type: str
    base_url: str
    external_id: str | None
    verify_tls: Literal[True] = True
    ca_cert_pem: str | None
    enabled: Literal[True] = True
    created_at: str
    updated_at: str
    credential: str | None = Field(default=None, repr=False)


class GitRuntimePolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    local_first_guidance: bool
    local_git_transport_enabled: bool
    remote_source_mutations_enabled: bool


class GitLabPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    protected_branches: list[str]


class GitHubPolicy(GitLabPolicy):
    required_checks: list[str]
    required_reviewers: list[str]


class InvocationPolicies(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    github: GitHubPolicy | None = None
    github_runtime: GitRuntimePolicy | None = None
    gitlab: GitLabPolicy | None = None
    gitlab_runtime: GitRuntimePolicy | None = None


class InvocationContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    accounts: tuple[ProjectAccount, ...]
    policies: InvocationPolicies | None = None


class InvocationLease(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    context: InvocationContext
    expires_at: StrictInt
