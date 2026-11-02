"""Node Git transport: credentials live only in one authorized child process.

Never install a credential helper or execute project hooks. The original
provider HTTP clients and branch policies remain authoritative.
"""

from __future__ import annotations

import base64
import re
import shutil
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from hand_runtime.provider_egress import ProviderConnection
from modules.github.application.merge import LocalWorktreeCleanup
from modules.github.github_identity import GitHubPrettyIdentityClient
from modules.github.infrastructure.schemas.repository import RepositoryVisibility
from modules.gitlab.gitlab_client import GitLabClient
from modules.gitlab.policy import require_mutable_branch
from service_runtime.http_transport import PooledHttpTransport

from .application.checkout import CheckoutRepository
from .application.cleanup_worktrees import CleanupMergedWorktrees
from .application.local_git import AuthorizeLocalGit, PushLocalGit
from .domain.local_git import CheckoutReceipt, CheckoutRequest, LocalGitAuthorization, LocalGitPush
from .infrastructure.checkout import GitCheckoutStorage
from .infrastructure.checkout import canonical_repository as _canonical
from .infrastructure.git_process import run_git as _git
from .infrastructure.git_worktrees import GitWorktreeStorage
from .infrastructure.local_git import GitWorkspace, LocalCheckout
from .node_proxy import provider_connection


class LocalRepository(Protocol):
    workspace_root: Path

    def _expected_remote(self, repository: str) -> str: ...


def _checkout(
    client: LocalCheckout,
    destination: str,
    clone_url: str,
    auth_scope: str,
    auth_header: str,
    *,
    mode: str = "snapshot",
    ref: str = "",
    overwrite: bool = False,
    branch: str = "",
) -> CheckoutReceipt:
    request = CheckoutRequest(mode, ref, branch, overwrite)
    storage = GitCheckoutStorage(client, destination, clone_url, auth_scope, auth_header)
    return CheckoutRepository(storage).execute(request)


def _cleanup_merged(
    client: LocalRepository, repository: str, branch: str, expected_head: str
) -> LocalWorktreeCleanup:
    root = client.workspace_root.resolve()
    canonical = _canonical(root, client._expected_remote(repository))
    return CleanupMergedWorktrees(GitWorktreeStorage(root, canonical)).execute(
        branch, expected_head
    )


class NodeGitHubClient(GitHubPrettyIdentityClient):
    def __post_init__(self) -> None:
        self._transport = PooledHttpTransport(
            lambda: provider_connection("https://api.github.com"),
            max_connections=self.max_connections,
            acquire_timeout=30,
            span_name="provider.github.http",
            provider="github",
        )

    def checkout_repository(
        self,
        repository: str,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> CheckoutReceipt:
        repository = self._assert_allowed(repository)
        token = self.token
        if not token:
            try:
                token = self._installation_token(repository)
            except Exception as exc:
                if "is not installed for GitHub App" not in str(exc):
                    raise
                response = self._request_model(
                    "GET",
                    "https://api.github.com/repos/" + repository,
                    response_type=RepositoryVisibility,
                )
                if response.status != 200 or response.data.private is not False:
                    raise ValueError("Public repository visibility required") from exc
        return _checkout(
            self,
            destination,
            self._expected_remote(repository),
            "https://github.com/",
            self._git_authorization_header(token),
            mode=mode,
            ref=ref,
            overwrite=overwrite,
        )

    def _delete_source_branch_cas(self, repository: str, branch: str, expected_head: str) -> None:
        repository = self._assert_allowed(repository)
        branch = require_mutable_branch(branch, self.protected_branches)
        if not re.fullmatch(r"[a-fA-F0-9]{40}", expected_head):
            raise ValueError("Exact expected branch SHA required")
        root = self.workspace_root.resolve()
        cache = _canonical(root, self._expected_remote(repository)).parent
        temporary = cache / (".delete-" + uuid4().hex)
        token = self.token or self._installation_token(repository)
        if not token:
            raise ValueError("Current selected account credential required")
        try:
            _git(root, "init", "--bare", "--template=", str(temporary))
            _git(temporary, "check-ref-format", "refs/heads/" + branch)
            _git(
                temporary,
                "push",
                "--porcelain",
                "--force-with-lease=refs/heads/" + branch + ":" + expected_head,
                "--",
                self._expected_remote(repository),
                ":refs/heads/" + branch,
                auth_scope="https://github.com/",
                auth_header=self._git_authorization_header(token),
            )
        finally:
            if temporary.exists() and temporary.resolve().is_relative_to(cache.resolve()):
                shutil.rmtree(temporary)

    def create_worktree(
        self, repository: str, destination: str, branch: str, ref: str = ""
    ) -> CheckoutReceipt:
        repository = self._assert_allowed(repository)
        token = self.token or self._installation_token(repository)
        return _checkout(
            self,
            destination,
            self._expected_remote(repository),
            "https://github.com/",
            self._git_authorization_header(token),
            mode="git",
            ref=ref,
            branch=branch,
        )

    def _cleanup_merged_worktrees(
        self, repository: str, branch: str, expected_head: str
    ) -> LocalWorktreeCleanup:
        return _cleanup_merged(self, repository, branch, expected_head)

    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> LocalGitAuthorization:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise ValueError("Authenticated selected account required")
        return AuthorizeLocalGit(GitWorkspace(self)).execute(
            repository, destination, remote, self._expected_remote(repository)
        )

    def push_local_git(
        self,
        repository: str,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> LocalGitPush:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise ValueError("Authenticated selected account required")
        token = self.token or self._installation_token(repository)
        encoded = base64.b64encode(("x-access-token:" + token).encode()).decode("ascii")
        return PushLocalGit(
            GitWorkspace(self), "https://github.com/", "Authorization: Basic " + encoded
        ).execute(
            repository,
            destination,
            remote,
            self._expected_remote(repository),
            branch,
            set_upstream,
        )


class NodeGitLabClient(GitLabClient):
    def _new_connection(self) -> ProviderConnection:
        return provider_connection(
            self.profile.base_url,
            verify_tls=self.profile.verify_tls,
            ca_cert_pem=self.profile.ca_cert_pem,
            timeout=30,
        )

    def checkout_repository(
        self,
        project: str | int,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> CheckoutReceipt:
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        encoded = base64.b64encode((username + ":" + self.profile.token()).encode()).decode("ascii")
        return _checkout(
            self,
            destination,
            self._expected_remote(str(project)),
            self.profile.base_url.rstrip("/") + "/",
            "Authorization: Basic " + encoded,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
        )

    def create_worktree(
        self, project: str | int, destination: str, branch: str, ref: str = ""
    ) -> CheckoutReceipt:
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        encoded = base64.b64encode((username + ":" + self.profile.token()).encode()).decode("ascii")
        return _checkout(
            self,
            destination,
            self._expected_remote(str(project)),
            self.profile.base_url.rstrip("/") + "/",
            "Authorization: Basic " + encoded,
            mode="git",
            ref=ref,
            branch=branch,
        )

    def _cleanup_merged_worktrees(
        self, repository: str, branch: str, expected_head: str
    ) -> LocalWorktreeCleanup:
        return _cleanup_merged(self, repository, branch, expected_head)

    def authorize_local_git(
        self, project: str | int, destination: str, *, remote: str = "origin"
    ) -> LocalGitAuthorization:
        if self.anonymous_only:
            raise ValueError("Authenticated selected account required")
        return AuthorizeLocalGit(GitWorkspace(self)).execute(
            str(project), destination, remote, self._expected_remote(str(project))
        )

    def push_local_git(
        self,
        project: str | int,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
        expected_remote_sha: str = "",
    ) -> LocalGitPush:
        if self.anonymous_only:
            raise ValueError("Authenticated selected account required")
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        encoded = base64.b64encode((username + ":" + self.profile.token()).encode()).decode("ascii")
        return PushLocalGit(
            GitWorkspace(self),
            self.profile.base_url.rstrip("/") + "/",
            "Authorization: Basic " + encoded,
        ).execute(
            str(project),
            destination,
            remote,
            self._expected_remote(str(project)),
            branch,
            set_upstream,
            expected_remote_sha,
        )
