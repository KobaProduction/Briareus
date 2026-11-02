from __future__ import annotations

from collections.abc import Callable

from mcp.types import ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar

from .models import GitLabCommitAction
from .repository import GitLabRepositoryOperations
from .repository_views import (
    RepositoryActions,
    RepositoryBranches,
    RepositoryCommit,
    RepositoryCommits,
    RepositoryComparison,
    RepositoryFile,
    RepositorySearch,
    RepositoryTree,
)


def register_repository_reads[CheckoutT, AuthorizationT, PushT](
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabRepositoryOperations[CheckoutT, AuthorizationT, PushT]],
    read_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitLab get file", annotations=read_annotations)
    def get_file(account_id: str, project: str, path: str, ref: str = "main") -> RepositoryFile:
        """Read one UTF-8 repository file."""
        return client_factory(account_id).get_file(project, path, ref)

    @mcp.tool(title="GitLab repository tree", annotations=read_annotations)
    def list_tree(
        account_id: str,
        project: str,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> RepositoryTree:
        """List repository tree entries."""
        return client_factory(account_id).list_tree(project, path, ref, recursive, page, per_page)

    @mcp.tool(title="GitLab code search", annotations=read_annotations)
    def search_code(
        account_id: str,
        project: str,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> RepositorySearch:
        """Search repository blobs inside one project."""
        return client_factory(account_id).search_code(project, search, ref, page, per_page)

    @mcp.tool(title="GitLab list commits", annotations=read_annotations)
    def list_commits(
        account_id: str,
        project: str,
        ref: str = "",
        path: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> RepositoryCommits:
        """List repository commit history, optionally filtered by ref and path."""
        return client_factory(account_id).list_commits(project, ref, path, page, per_page)

    @mcp.tool(title="GitLab get commit", annotations=read_annotations)
    def get_commit(account_id: str, project: str, sha: str) -> RepositoryCommit:
        """Read one commit together with its repository diff."""
        return client_factory(account_id).get_commit(project, sha)


def register_repository_commits[CheckoutT, AuthorizationT, PushT](
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabRepositoryOperations[CheckoutT, AuthorizationT, PushT]],
    write_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitLab atomic commit", annotations=write_annotations)
    def commit_actions(
        account_id: str,
        project: str,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> RepositoryActions:
        """Create one atomic multi-file commit using GitLab repository commit actions."""
        return client_factory(account_id).commit_actions(
            project, branch, commit_message, actions, start_branch
        )


def register_repository_branches[CheckoutT, AuthorizationT, PushT](
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabRepositoryOperations[CheckoutT, AuthorizationT, PushT]],
    read_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitLab list branches", annotations=read_annotations)
    def list_branches(
        account_id: str, project: str, search: str = "", page: int = 1, per_page: int = 100
    ) -> RepositoryBranches:
        """List repository branches."""
        return client_factory(account_id).list_branches(project, search, page, per_page)


def register_repository_comparison[CheckoutT, AuthorizationT, PushT](
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabRepositoryOperations[CheckoutT, AuthorizationT, PushT]],
    read_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitLab compare refs", annotations=read_annotations)
    def compare(
        account_id: str, project: str, from_ref: str, to_ref: str, straight: bool = False
    ) -> RepositoryComparison:
        """Compare two repository refs."""
        return client_factory(account_id).compare(project, from_ref, to_ref, straight)
