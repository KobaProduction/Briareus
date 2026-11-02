"""Typed GitLab checkout, local credential setup and push receipts."""

from pydantic import BaseModel

from service_runtime.checkout_contracts import RepositoryCheckout


class GitLabCheckout(RepositoryCheckout):
    project: str
    profile_id: str


class GitLabGitAuthorization(BaseModel):
    authorized: bool
    project: str
    workspace: str
    remote: str
    remote_url: str
    branch: str
    account_id: str
    credential_storage: str
    credential_file: str
    push_mode: str


class GitLabGitPush(BaseModel):
    pushed: bool
    project: str
    workspace: str
    remote: str
    branch: str
    head: str
    account_id: str
    force_with_lease: bool
    expected_remote_sha: str | None
    git_output: str
