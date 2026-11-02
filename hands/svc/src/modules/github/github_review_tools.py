from __future__ import annotations

from collections.abc import Callable as Callable

from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from source_control.providers.github.review_registration import (
    register_github_branch_review,
    register_github_inline_comments,
)

from .execution_views import ConversationComments as ConversationComments
from .execution_views import ReviewBranchUpdate as ReviewBranchUpdate
from .execution_views import ReviewComments as ReviewComments
from .github_review import GitHubReviewClient as GitHubReviewClient


def register_github_review_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubReviewClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register rebase and detailed review tools."""
    register_github_branch_review(mcp, client_factory, write_annotations)

    @mcp.tool(title="GitHub agent conversation comments", annotations=read_annotations)
    def github_agent_list_conversation_comments(
        account_id: str,
        repository: str,
        number: int,
        page: int = 1,
        per_page: int = 100,
    ) -> ConversationComments:
        """List one page of top-level issue/PR comments; use next_page to continue."""
        return client_factory(account_id).list_conversation_comments(
            repository, number, page, per_page
        )

    register_github_inline_comments(mcp, client_factory, read_annotations)
