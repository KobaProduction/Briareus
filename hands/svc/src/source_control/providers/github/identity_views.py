"""Typed GitHub actor observations and branch administration receipts."""

from pydantic import BaseModel, ConfigDict


class GitHubActor(BaseModel):
    model_config = ConfigDict(frozen=True)
    source: str
    login: str
    id: int
    name: str
    email: str
    display_name: str | None = None
    type: str | None = None
    app_id: str = ""
    slug: str = ""
    reader_account: str | None = None
    transport_authenticated: bool | None = None


class RepositoryPermissions(BaseModel):
    contents: str = "none"
    workflows: str = "none"
    pull_requests: str = "none"
    issues: str = "none"
    actions: str = "none"
    checks: str = "none"
    repository_push: bool | None = None
    repository_admin: bool | None = None
    repository_maintain: bool | None = None


class RepositoryFacts(BaseModel):
    default_branch: str
    fork: bool
    archived: bool


class MutationCapabilities(BaseModel):
    branch_delete: bool
    force_ref_update: bool
    history_identity_rewrite: bool


class BranchPolicy(BaseModel):
    reserved_branches: list[str]
    reserved_branch_mutation_allowed: bool


class RepositoryCapabilities(BaseModel):
    repository: str
    allowed_repository: bool
    auth_type: str
    app_id: str | None
    installation_id: int | None
    agent_identity: GitHubActor
    repository_metadata: RepositoryFacts
    permissions: RepositoryPermissions
    capabilities: MutationCapabilities
    bridge_policy: BranchPolicy


class ReservedBranchRepoint(BaseModel):
    repository: str
    branch: str
    old_head_sha: str
    new_head_sha: str
    tree_sha: str
    content_changed: bool
    bridge_reserved: bool
    github_protected: bool
    agent_identity: GitHubActor
    dry_run: bool
    ref_updated: bool
    status: str = ""
