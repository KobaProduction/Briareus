from __future__ import annotations

from collections.abc import Callable as Callable

from mcp.types import CallToolResult as CallToolResult
from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from source_control.providers.gitlab.repository_registration import (
    register_repository_branches,
    register_repository_commits,
    register_repository_comparison,
    register_repository_reads,
)
from svc_hand.local_git_result import local_git_result as local_git_result

from .gitlab_client import GitLabClient as GitLabClient
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


def register_gitlab_repository_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitLab checkout repository", annotations=write_annotations)
    def checkout_repository(
        account_id: str,
        project: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> CallToolResult:
        """Checkout a GitLab repository into the shared workspace.

        mode='snapshot' exports files; mode='git' creates an agent worktree
        backed by one canonical repository. Existing destinations are preserved.
        account_id may be a stable account alias.
        """
        return local_git_result(
            client_factory(account_id).checkout_repository(
                project,
                destination,
                mode=mode,
                ref=ref,
                overwrite=overwrite,
            )
        )

    @mcp.tool(title="GitLab create agent worktree", annotations=write_annotations)
    def create_worktree(
        account_id: str, project: str, destination: str, branch: str, ref: str = ""
    ) -> CallToolResult:
        """Reuse one current-project repository; create a separate branch/\
worktree without overwriting data."""
        return local_git_result(
            client_factory(account_id).create_worktree(project, destination, branch, ref)
        )

    @mcp.tool(title="Authorize local Git workspace", annotations=write_annotations)
    def authorize_local_git(
        account_id: str,
        project: str,
        destination: str,
        remote: str = "origin",
    ) -> CallToolResult:
        """Authorize an existing GitLab checkout for secure ordinary Git transport."""
        return local_git_result(
            client_factory(account_id).authorize_local_git(
                project,
                destination,
                remote=remote,
            )
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
    ) -> CallToolResult:
        """Push local Git HEAD, optionally using CAS-safe force-with-lease."""
        return local_git_result(
            client_factory(account_id).push_local_git(
                project,
                destination,
                branch=branch,
                remote=remote,
                set_upstream=set_upstream,
                expected_remote_sha=expected_remote_sha,
            )
        )

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
        """Create or update a UTF-8 file if permitted by GitLab."""
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
        """Delete a file if permitted by GitLab."""
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
        """Create a branch from a ref, subject to optional Bridge and GitLab policy."""
        return client_factory(account_id).create_branch(project, branch, ref)

    @mcp.tool(title="GitLab delete branch", annotations=destructive_annotations)
    def delete_branch(
        account_id: str,
        project: str,
        branch: str,
    ) -> RepositoryBranchDeleted:
        """Delete a branch if permitted by GitLab and optional Bridge policy."""
        return client_factory(account_id).delete_branch(project, branch)

    register_repository_comparison(mcp, client_factory, read_annotations)
