from __future__ import annotations

from collections.abc import Callable

from briareus_git.tags import register_tag_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_actions import GitHubActionsClient


def register_github_ref_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub list commits", annotations=read_annotations)
    def list_commits(
        account_id: str,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """List commit history, optionally filtered by ref and path."""
        return client_factory(account_id).list_commits(repository, ref, path, per_page, page)

    @mcp.tool(title="GitHub get commit", annotations=read_annotations)
    def get_commit(account_id: str, repository: str, ref: str) -> JsonObject:
        """Read one commit including changed-file statistics and patches when available."""
        return client_factory(account_id).get_commit(repository, ref)

    @mcp.tool(title="GitHub delete branch", annotations=destructive_annotations)
    def delete_branch(account_id: str, repository: str, branch: str) -> JsonObject:
        """Delete a non-protected branch."""
        return client_factory(account_id).delete_branch(repository, branch)

    @mcp.tool(title="GitHub rename branch", annotations=write_annotations)
    def rename_branch(
        account_id: str,
        repository: str,
        branch: str,
        new_name: str,
    ) -> JsonObject:
        """Rename a non-protected branch to another non-protected name."""
        return client_factory(account_id).rename_branch(repository, branch, new_name)

    @mcp.tool(title="GitHub reset branch", annotations=destructive_annotations)
    def reset_branch(
        account_id: str,
        repository: str,
        branch: str,
        target_ref: str,
        expected_head_sha: str,
        allow_protected_branch: bool = False,
        dry_run: bool = True,
    ) -> JsonObject:
        """Reset a branch to an existing ancestor commit after CAS validation.

        Protected branches require explicit allow_protected_branch=true. The operation
        defaults to dry-run and refuses non-ancestor targets.
        """
        return client_factory(account_id).reset_branch(
            repository,
            branch,
            target_ref,
            expected_head_sha,
            allow_protected_branch,
            dry_run,
        )

    register_tag_tools(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations, "GitHub"
    )
