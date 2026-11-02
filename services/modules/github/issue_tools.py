from __future__ import annotations

from collections.abc import Callable as Callable

from fastmcp import FastMCP as FastMCP
from mcp.types import ToolAnnotations as ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar as ToolRegistrar
from source_control.providers.github.issue_registration import register_github_issue_changes

from .collaboration_views import CommentCreated as CommentCreated
from .collaboration_views import IssueList as IssueList
from .collaboration_views import IssueResponse as IssueResponse
from .github_actions import GitHubActionsClient as GitHubActionsClient


def register_github_issue_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitHub agent list issues", annotations=read_annotations)
    def github_agent_list_issues(
        account_id: str,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> IssueList:
        """List issues, excluding pull requests."""
        return client_factory(account_id).list_issues(repository, state, per_page, page)

    register_github_issue_changes(mcp, client_factory, read_annotations, write_annotations)
