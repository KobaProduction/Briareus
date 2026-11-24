from __future__ import annotations

from collections.abc import Callable

from briareus_git.provider_tools import register_issue_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_actions import GitHubActionsClient


def register_github_issue_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    register_issue_tools(mcp, client_factory, read_annotations, write_annotations, "GitHub")

    @mcp.tool(title="GitHub list issues", annotations=read_annotations)
    def list_issues(
        account_id: str,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        """List issues, excluding pull requests."""
        return client_factory(account_id).list_issues(repository, state, per_page, page)

    @mcp.tool(title="GitHub issue/PR conversation comment", annotations=write_annotations)
    def add_issue_comment(
        account_id: str,
        repository: str,
        number: int,
        body: str,
    ) -> JsonObject:
        """Add a top-level conversation comment to an issue or pull request."""
        return client_factory(account_id).add_issue_comment(repository, number, body)

    @mcp.tool(title="GitHub update issue comment", annotations=write_annotations)
    def update_issue_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        body: str,
    ) -> JsonObject:
        """Edit a top-level issue/PR conversation comment.

        GitHub enforces authorship/permissions.
        """
        return client_factory(account_id).update_issue_comment(repository, comment_id, body)

    @mcp.tool(title="GitHub delete issue comment", annotations=write_annotations)
    def delete_issue_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        confirm: bool = False,
    ) -> JsonObject:
        """Permanently delete a top-level issue comment after explicit confirmation."""
        return client_factory(account_id).delete_issue_comment(repository, comment_id, confirm)
