from __future__ import annotations

from collections.abc import Callable

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_collab import GitHubCollabClient
from .models import ReviewComment


def register_github_collab_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubCollabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register collaboration and review-thread workflow tools."""
    _register_review_mutations(mcp, client_factory, write_annotations)

    @mcp.tool(title="GitHub merge working branches", annotations=write_annotations)
    def merge_branch(
        account_id: str,
        repository: str,
        base: str,
        head: str,
        commit_message: str | None = None,
    ) -> JsonObject:
        """Merge one ref into a non-protected working branch."""
        return client_factory(account_id).merge_branch(repository, base, head, commit_message)

    @mcp.tool(title="GitHub request reviewers", annotations=write_annotations)
    def request_reviewers(
        account_id: str,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> JsonObject:
        """Request users or teams to review a pull request."""
        return client_factory(account_id).request_reviewers(
            repository,
            number,
            reviewers,
            team_reviewers,
        )

    @mcp.tool(title="GitHub remove requested reviewers", annotations=write_annotations)
    def remove_requested_reviewers(
        account_id: str,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> JsonObject:
        """Remove user/team review requests from a pull request."""
        return client_factory(account_id).remove_requested_reviewers(
            repository,
            number,
            reviewers,
            team_reviewers,
        )

    @mcp.tool(title="GitHub list review threads", annotations=read_annotations)
    def list_review_threads(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List inline review threads including resolved/outdated state."""
        return client_factory(account_id).list_review_threads(repository, number)

    @mcp.tool(title="GitHub mark pull ready", annotations=write_annotations)
    def mark_pull_ready_for_review(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Mark a draft pull request ready for review."""
        return client_factory(account_id).mark_pull_ready_for_review(repository, number)

    @mcp.tool(title="GitHub required reviews", annotations=read_annotations)
    def required_reviews(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """Verify configured required approvals before merge."""
        return client_factory(account_id).assert_required_reviews(repository, number)


def _register_review_mutations(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubCollabClient],
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub rich review", annotations=write_annotations)
    def create_review(
        account_id: str,
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: list[ReviewComment] | None = None,
        commit_id: str | None = None,
    ) -> JsonObject:
        """Submit COMMENT, APPROVE, or REQUEST_CHANGES with optional inline comments."""
        return client_factory(account_id).create_review_with_comments(
            repository,
            number,
            event,
            body,
            comments,
            commit_id,
        )

    @mcp.tool(title="GitHub merge pull request", annotations=write_annotations)
    def merge_pull_request(
        account_id: str,
        repository: str,
        number: int,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        """Merge a same-repository PR after validating its current head and required checks."""
        return client_factory(account_id).merge_pull_request(
            repository,
            number,
            merge_method,
            commit_title,
            commit_message,
            expected_head_sha,
        )

    @mcp.tool(title="GitHub update review comment", annotations=write_annotations)
    def update_review_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        body: str,
    ) -> JsonObject:
        """Replace the body of an inline review comment."""
        return client_factory(account_id).update_review_comment(
            repository,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub reply to comment", annotations=write_annotations)
    def reply_to_review_comment(
        account_id: str,
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> JsonObject:
        """Reply inside an inline review thread."""
        return client_factory(account_id).reply_to_review_comment(
            repository,
            number,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub set thread state", annotations=write_annotations)
    def set_review_thread_resolved(
        account_id: str,
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> JsonObject:
        """Resolve or reopen one review thread."""
        return client_factory(account_id).set_review_thread_resolved(
            repository,
            thread_id,
            resolved,
        )
