from __future__ import annotations

from collections.abc import Callable

from mcp.types import ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar

from .execution_views import ReviewBranchUpdate, ReviewComments
from .github_review import GitHubReviewClient


def register_github_branch_review(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubReviewClient],
    write_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitHub agent update pull branch with method", annotations=write_annotations)
    def github_agent_update_pull_branch_method(
        account_id: str,
        repository: str,
        number: int,
        method: str = "MERGE",
        expected_head_sha: str | None = None,
    ) -> ReviewBranchUpdate:
        """Update a PR branch using MERGE or true REBASE through GitHub GraphQL."""
        return client_factory(account_id).update_pull_branch_graphql(
            repository, number, method, expected_head_sha
        )


def register_github_inline_comments(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubReviewClient],
    read_annotations: ToolAnnotations,
) -> None:

    @mcp.tool(title="GitHub agent inline review comments", annotations=read_annotations)
    def github_agent_list_review_comments(
        account_id: str, repository: str, number: int
    ) -> ReviewComments:
        """List inline review comments for a pull request."""
        return client_factory(account_id).list_review_comments(repository, number)
