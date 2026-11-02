"""Flat receipts for the existing provider-managed local Git transport."""

from pydantic import BaseModel

from service_runtime.checkout_contracts import RepositoryCheckout


class WorkspaceGitAuthorization(BaseModel):
    authorized: bool
    repository: str
    workspace: str
    resolved_workspace_path: str
    remote: str
    remote_url: str
    branch: str
    account_id: str
    credential_storage: str
    credential_file: str
    push_mode: str
    warning: str


class WorkspaceGitPush(BaseModel):
    pushed: bool
    repository: str
    workspace: str
    resolved_workspace_path: str
    remote: str
    branch: str
    head: str
    account_id: str
    credential_storage: str
    git_output: str
    warning: str


class GitHubCheckout(RepositoryCheckout):
    repository: str
