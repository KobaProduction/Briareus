"""Credential-free GitLab profile and project inspection results."""

from pydantic import BaseModel, ConfigDict, Field

from .infrastructure.schemas.identity import AuthenticatedGitLabUser, GitLabVersion
from .infrastructure.schemas.projects import GitLabProject


class PublicGitLabProfile(BaseModel):
    account_id: str
    alias: str
    base_url: str
    api_url: str
    auth_type: str
    credential_configured: bool
    verify_tls: bool
    ca_cert_pem_configured: bool


class GitLabProfileStatus(BaseModel):
    account: PublicGitLabProfile
    authenticated_user: AuthenticatedGitLabUser | None
    gitlab_version: GitLabVersion | None
    status: str
    access_mode: str | None = None


class UnknownPermissions(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PublicPermissions(BaseModel):
    repository: str


class TokenPermissions(BaseModel):
    scopes: list[str]
    active: bool | None
    expires_at: str | None


class ProjectAccess(BaseModel):
    access_level: int
    access_level_name: str


class ProjectAccesses(BaseModel):
    project_access: ProjectAccess | None = None
    group_access: ProjectAccess | None = None


class ProjectScope(BaseModel):
    selector: str
    id: int
    path_with_namespace: str
    visibility: str
    access: ProjectAccesses


class GitLabAccountCapabilities(BaseModel):
    account: PublicGitLabProfile
    auth_type: str
    provider_permissions_known: bool
    provider_permissions: TokenPermissions | PublicPermissions | UnknownPermissions
    note: str | None = None
    project: ProjectScope | None = None
    potential_capabilities: list[str] = Field(default_factory=list)
    permission_scope: str | None = None


class GitLabProjectList(BaseModel):
    account_id: str
    projects: list[GitLabProject]
    page: int
    per_page: int
    next_page: str
    total: int | None
    total_pages: int | None


class GitLabProjectStatus(BaseModel):
    account_id: str
    project: GitLabProject
