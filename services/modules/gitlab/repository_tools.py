from __future__ import annotations

from collections.abc import Callable as Callable

from fastmcp import FastMCP as FastMCP
from mcp.types import ToolAnnotations as ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar as ToolRegistrar
from source_control.providers.gitlab.repository_registration import (
    register_repository_branches,
    register_repository_commits,
    register_repository_comparison,
    register_repository_reads,
)

from .gitlab_client import GitLabClient as GitLabClient
from .local_git_views import GitLabCheckout as GitLabCheckout
from .local_git_views import GitLabGitAuthorization as GitLabGitAuthorization
from .local_git_views import GitLabGitPush as GitLabGitPush
from .models import GitLabCommitAction as GitLabCommitAction
from .repository_views import RepositoryActions as RepositoryActions
from .repository_views import RepositoryBranchCreated as RepositoryBranchCreated
from .repository_views import RepositoryBranchDeleted as RepositoryBranchDeleted
from .repository_views import RepositoryBranches as RepositoryBranches
from .repository_views import RepositoryCommit as RepositoryCommit
from .repository_views import RepositoryCommits as RepositoryCommits
from .repository_views import RepositoryComparison as RepositoryComparison
from .repository_views import RepositoryFile as RepositoryFile
from .repository_views import RepositoryFileDelete as RepositoryFileDelete
from .repository_views import RepositoryFileWrite as RepositoryFileWrite
from .repository_views import RepositorySearch as RepositorySearch
from .repository_views import RepositoryTree as RepositoryTree


def _register_local_git_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabClient],
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab checkout repository", annotations=write_annotations)
    def checkout_repository(
        account_id: str,
        project: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> GitLabCheckout:
        """Checkout a GitLab repository into the shared workspace.

        mode='snapshot' creates a shallow working tree without .git.
        mode='git' keeps full Git metadata and history.
        account_id may be a stable account alias.
        """
        return client_factory(account_id).checkout_repository(
            project,
            destination,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
        )

    @mcp.tool(title="Authorize local Git workspace", annotations=write_annotations)
    def authorize_local_git(
        account_id: str,
        project: str,
        destination: str,
        remote: str = "origin",
    ) -> GitLabGitAuthorization:
        """Authorize an existing GitLab checkout for secure ordinary Git transport."""
        return client_factory(account_id).authorize_local_git(
            project,
            destination,
            remote=remote,
        )

    @mcp.tool(title="Push local Git workspace", annotations=write_annotations)
    def push_local_git(
        account_id: str,
        project: str,
        destination: str,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
        expected_remote_sha: str = "",
    ) -> GitLabGitPush:
        """Push local Git HEAD, optionally using CAS-safe force-with-lease."""
        return client_factory(account_id).push_local_git(
            project,
            destination,
            branch=branch,
            remote=remote,
            set_upstream=set_upstream,
            expected_remote_sha=expected_remote_sha,
        )


def register_gitlab_repository_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    _register_local_git_tools(mcp, client_factory, write_annotations)
    register_repository_reads(mcp, client_factory, read_annotations)

    @mcp.tool(title="GitLab put file", annotations=write_annotations)
    def put_file(
        account_id: str,
        project: str,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> RepositoryFileWrite:
        """Create or update one UTF-8 file on a non-protected branch."""
        return client_factory(account_id).put_file(
            project, path, content, branch, commit_message, last_commit_id
        )

    @mcp.tool(title="GitLab delete file", annotations=destructive_annotations)
    def delete_file(
        account_id: str,
        project: str,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> RepositoryFileDelete:
        """Delete one file on a non-protected branch."""
        return client_factory(account_id).delete_file(
            project, path, branch, commit_message, last_commit_id
        )

    register_repository_commits(mcp, client_factory, write_annotations)
    register_repository_branches(mcp, client_factory, read_annotations)

    @mcp.tool(title="GitLab create branch", annotations=write_annotations)
    def create_branch(
        account_id: str,
        project: str,
        branch: str,
        ref: str,
    ) -> RepositoryBranchCreated:
        """Create a non-protected branch from a ref."""
        return client_factory(account_id).create_branch(project, branch, ref)

    @mcp.tool(title="GitLab delete branch", annotations=destructive_annotations)
    def delete_branch(
        account_id: str,
        project: str,
        branch: str,
    ) -> RepositoryBranchDeleted:
        """Delete a non-protected repository branch."""
        return client_factory(account_id).delete_branch(project, branch)

    register_repository_comparison(mcp, client_factory, read_annotations)
