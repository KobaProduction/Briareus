from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from mcp.types import CallToolResult, ToolAnnotations

from hand_runtime.provider_schemas import JSON_OBJECT_OUTPUT_SCHEMA

from .collaboration_views import (
    BranchAlreadyMerged,
    BranchMerged,
    PullReady,
    RemovedReviewers,
    RequestedReviewers,
    ReviewThreads,
)
from .contracts import ToolRegistrar
from .github_collab import GitHubCollabClient
from .review_result import review_result


def register_github_collab_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubCollabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register collaboration and review-thread workflow tools."""

    @mcp.tool(title="GitHub agent merge working branches", annotations=write_annotations)
    def github_agent_merge_branch(
        account_id: str,
        repository: str,
        base: str,
        head: str,
        commit_message: str | None = None,
    ) -> BranchMerged | BranchAlreadyMerged:
        """Merge one ref into a non-protected working branch."""
        return client_factory(account_id).merge_branch(repository, base, head, commit_message)

    @mcp.tool(title="GitHub agent request reviewers", annotations=write_annotations)
    def github_agent_request_reviewers(
        account_id: str,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> RequestedReviewers:
        """Request users or teams to review a pull request."""
        return client_factory(account_id).request_reviewers(
            repository,
            number,
            reviewers,
            team_reviewers,
        )

    @mcp.tool(title="GitHub agent remove requested reviewers", annotations=write_annotations)
    def github_agent_remove_requested_reviewers(
        account_id: str,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> RemovedReviewers:
        """Remove user/team review requests from a pull request."""
        return client_factory(account_id).remove_requested_reviewers(
            repository,
            number,
            reviewers,
            team_reviewers,
        )

    @mcp.tool(title="GitHub agent list review threads", annotations=read_annotations)
    def github_agent_list_review_threads(
        account_id: str,
        repository: str,
        number: int,
    ) -> ReviewThreads:
        """List inline review threads including resolved/outdated state."""
        return client_factory(account_id).list_review_threads(repository, number)

    @mcp.tool(title="GitHub agent mark pull ready", annotations=write_annotations)
    def github_agent_mark_pull_ready_for_review(
        account_id: str,
        repository: str,
        number: int,
    ) -> PullReady:
        """Mark a draft pull request ready for review."""
        return client_factory(account_id).mark_pull_ready_for_review(repository, number)

    @mcp.tool(
        title="GitHub agent required reviews",
        annotations=read_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_agent_required_reviews(
        account_id: str,
        repository: str,
        number: int,
    ) -> CallToolResult:
        """Verify configured required approvals before merge."""
        return review_result(client_factory(account_id).assert_required_reviews(repository, number))
