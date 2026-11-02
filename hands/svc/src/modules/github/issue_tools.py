from __future__ import annotations

from collections.abc import Callable as Callable

from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from source_control.providers.github.issue_registration import register_github_issue_changes

from .collaboration_views import CommentCreated as CommentCreated
from .collaboration_views import IssueCommentDeleted as IssueCommentDeleted
from .collaboration_views import IssueCommentUpdated as IssueCommentUpdated
from .collaboration_views import IssuePage as IssuePage
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
    ) -> IssuePage:
        """List issues, excluding pull requests."""
        return client_factory(account_id).list_issues(repository, state, per_page, page)

    register_github_issue_changes(mcp, client_factory, read_annotations, write_annotations)

    @mcp.tool(title="GitHub agent update issue comment", annotations=write_annotations)
    def github_agent_update_issue_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        body: str,
    ) -> IssueCommentUpdated:
        "Edit a top-level issue/PR conversation comment. GitHub enforces authorship/permissions."
        return client_factory(account_id).update_issue_comment(repository, comment_id, body)

    @mcp.tool(title="GitHub agent delete issue comment", annotations=write_annotations)
    def github_agent_delete_issue_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        confirm: bool = False,
    ) -> IssueCommentDeleted:
        """Permanently delete a top-level issue comment after explicit confirmation."""
        return client_factory(account_id).delete_issue_comment(repository, comment_id, confirm)
