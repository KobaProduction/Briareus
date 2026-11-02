from __future__ import annotations

from collections.abc import Callable

from mcp.types import ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar

from .collaboration_views import (
    CommentCreated,
    IssueResponse,
)
from .github_actions import GitHubActionsClient


def register_github_issue_changes(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitHub agent get issue", annotations=read_annotations)
    def github_agent_get_issue(account_id: str, repository: str, number: int) -> IssueResponse:
        """Read one issue."""
        return client_factory(account_id).get_issue(repository, number)

    @mcp.tool(title="GitHub agent create issue", annotations=write_annotations)
    def github_agent_create_issue(
        account_id: str,
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> IssueResponse:
        """Create an issue inside an allowlisted repository."""
        return client_factory(account_id).create_issue(repository, title, body, labels)

    @mcp.tool(title="GitHub agent update issue", annotations=write_annotations)
    def github_agent_update_issue(
        account_id: str,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> IssueResponse:
        """Update an issue inside an allowlisted repository."""
        return client_factory(account_id).update_issue(
            repository, number, title, body, state, labels
        )

    @mcp.tool(title="GitHub agent issue comment", annotations=write_annotations)
    def github_agent_add_issue_comment(
        account_id: str, repository: str, number: int, body: str
    ) -> CommentCreated:
        """Add a comment to an issue."""
        return client_factory(account_id).add_issue_comment(repository, number, body)
