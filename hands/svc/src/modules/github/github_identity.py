from __future__ import annotations

from source_control.providers.github.github_identity import _GITHUB_API as _GITHUB_API
from source_control.providers.github.github_identity import (
    GitHubPrettyIdentityClient as _SharedGitHubPrettyIdentityClient,
)
from svc_hand.domain.local_git import CheckoutReceipt, LocalGitAuthorization, LocalGitPush

from .account_views import GitHubAccountCapabilities as GitHubAccountCapabilities
from .account_views import ProviderIdentity as ProviderIdentity
from .domain.history import GitIdentity as GitIdentity
from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError as GitHubAgentError
from .identity_views import GitHubActor as GitHubActor
from .infrastructure.schemas.identity import AppRecord as AppRecord
from .infrastructure.schemas.identity import UserRecord as UserRecord
from .infrastructure.schemas.permissions import AppPermissions as AppPermissions
from .infrastructure.schemas.repository import AnnotatedTagCreate as AnnotatedTagCreate
from .infrastructure.schemas.repository import CommitAuthors as CommitAuthors
from .infrastructure.schemas.repository import GitSignatureRequest as GitSignatureRequest
from .local_git_views import WorkspaceGitAuthorization as WorkspaceGitAuthorization
from .local_git_views import WorkspaceGitPush as WorkspaceGitPush
from .provider_views import RepositoryList as RepositoryList
from .provider_views import RepositoryStatus as RepositoryStatus


class GitHubPrettyIdentityClient(_SharedGitHubPrettyIdentityClient, GitHubActionsClient):
    def create_worktree(
        self, repository: str, destination: str, branch: str, ref: str = ""
    ) -> CheckoutReceipt:
        del repository, destination, branch, ref
        raise GitHubAgentError("Project-scoped Node transport required for agent worktrees")

    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> WorkspaceGitAuthorization | LocalGitAuthorization:
        return self._authorize_local_git(repository, destination, remote=remote)

    def push_local_git(
        self,
        repository: str,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> WorkspaceGitPush | LocalGitPush:
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise GitHubAgentError("local Git push requires an authenticated GitHub account")
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        marker_repo = self._git_optional_output(
            target, "config", "--local", "--get", "koba.github.repository"
        )
        marker_account = self._git_optional_output(
            target, "config", "--local", "--get", "koba.github.accountId"
        )
        marker_enabled = self._git_optional_output(
            target, "config", "--local", "--get", "koba.github.transportAuthorized"
        )
        if (
            marker_repo != repository
            or marker_account != self.account_id
            or marker_enabled.casefold() != "true"
        ):
            raise GitHubAgentError(
                "workspace is not authorized for this GitHub account/repository; "
                "call github_authorize_local_git first"
            )
        current_branch = self._git_output(target, "branch", "--show-current")
        push_branch = (branch.strip() or current_branch).strip()
        if not push_branch:
            raise GitHubAgentError("cannot push a detached HEAD; specify a local branch")
        self._assert_branch_mutation_allowed(repository, push_branch)
        # Existing workspaces may retain our pre-push hook with the old deny-list.
        if not self.protected_branches:
            guard = target / ".git" / "hooks" / "pre-push"
            if guard.is_file() and "# koba-managed-local-git-guard" in guard.read_text(
                encoding="utf-8", errors="replace"
            ):
                guard.unlink()
        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        args += [remote, f"HEAD:refs/heads/{push_branch}"]
        output = self._git_output(target, *args)
        head = self._git_output(target, "rev-parse", "HEAD")
        return WorkspaceGitPush(
            pushed=True,
            repository=repository,
            workspace=target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            resolved_workspace_path=target.as_posix(),
            remote=remote,
            branch=push_branch,
            head=head,
            account_id=self.account_id,
            credential_storage="none",
            git_output=output[-2048:],
            warning="Experimental local Git transport. Existing GitHub mutation tools remain "
            "available until this path is fully accepted.",
        )
