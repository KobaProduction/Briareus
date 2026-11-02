from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy

from mcp.types import CallToolResult, ToolAnnotations

from hand_runtime.provider_schemas import JSON_OBJECT_OUTPUT_SCHEMA

from ._pull_read import _pull_request_reader
from .collaboration_views import (
    PullFiles,
    PullList,
    PullReviews,
    ReviewCommentReply,
    ReviewCommentUpdated,
    ReviewThreadResolution,
    ReviewThreads,
)
from .content_views import (
    DirectoryListing,
    RepositoryBinaryFile,
    RepositoryCodeSearch,
    RepositoryTextFile,
)
from .contracts import ToolRegistrar
from .execution_views import (
    ConversationComments,
    ReviewComments,
    ReviewCreation,
    WorkflowJobList,
    WorkflowRunList,
)
from .github_actions import GitHubActionsClient
from .merge_result import merge_result
from .models import ReviewComment
from .provider_views import RepositoryList, RepositoryStatus
from .ref_views import (
    BranchList,
    CommitList,
    CommitView,
    RepositoryComparison,
    TagList,
)
from .review_result import review_result


def register_github_reviewer_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    """Register repository evidence, pull gates, workflow evidence, then explicit review actions."""
    _register_repository_reads(mcp, client_factory, read_annotations)
    _register_pull_evidence(mcp, client_factory, read_annotations)
    _register_workflow_evidence(mcp, client_factory, read_annotations)
    _register_review_actions(mcp, client_factory, write_annotations)


def _register_repository_reads(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub reviewer list repositories", annotations=read_annotations)
    def github_reviewer_list_repositories(account_id: str) -> RepositoryList:
        """List repositories currently granted to the selected GitHub account."""
        return client_factory(account_id).list_repositories()

    @mcp.tool(title="GitHub reviewer status", annotations=read_annotations)
    def github_reviewer_status(account_id: str, repository: str) -> RepositoryStatus:
        """Verify the selected GitHub account for one repository."""
        return client_factory(account_id).status(repository)

    @mcp.tool(title="GitHub reviewer get file", annotations=read_annotations)
    def github_reviewer_get_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> RepositoryTextFile:
        """Read one UTF-8 file for review."""
        return client_factory(account_id).get_file(repository, path, ref)

    @mcp.tool(title="GitHub reviewer get binary file", annotations=read_annotations)
    def github_reviewer_get_binary_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> RepositoryBinaryFile:
        """Read one file as base64 for binary review."""
        return client_factory(account_id).get_binary_file(repository, path, ref)

    @mcp.tool(title="GitHub reviewer list directory", annotations=read_annotations)
    def github_reviewer_list_directory(
        account_id: str,
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> DirectoryListing:
        """List a directory for review."""
        return client_factory(account_id).list_directory(repository, path, ref)

    @mcp.tool(title="GitHub reviewer list branches", annotations=read_annotations)
    def github_reviewer_list_branches(account_id: str, repository: str) -> BranchList:
        """List branches without exposing branch mutation."""
        return client_factory(account_id).list_branches(repository)

    @mcp.tool(title="GitHub reviewer list tags", annotations=read_annotations)
    def github_reviewer_list_tags(
        account_id: str,
        repository: str,
        per_page: int = 100,
        page: int = 1,
    ) -> TagList:
        """List repository tags without exposing tag mutation."""
        return client_factory(account_id).list_tags(repository, per_page, page)

    @mcp.tool(title="GitHub reviewer compare refs", annotations=read_annotations)
    def github_reviewer_compare(
        account_id: str,
        repository: str,
        base: str,
        head: str,
    ) -> RepositoryComparison:
        """Compare two refs for review."""
        return client_factory(account_id).compare(repository, base, head)

    @mcp.tool(title="GitHub reviewer list commits", annotations=read_annotations)
    def github_reviewer_list_commits(
        account_id: str,
        repository: str,
        ref: str | None = None,
        path: str | None = None,
        per_page: int = 50,
        page: int = 1,
    ) -> CommitList:
        """Read commit history for review."""
        return client_factory(account_id).list_commits(repository, ref, path, per_page, page)

    @mcp.tool(title="GitHub reviewer get commit", annotations=read_annotations)
    def github_reviewer_get_commit(account_id: str, repository: str, ref: str) -> CommitView:
        """Read one commit and changed-file patches."""
        return client_factory(account_id).get_commit(repository, ref)

    @mcp.tool(title="GitHub reviewer search code", annotations=read_annotations)
    def github_reviewer_search_code(
        account_id: str,
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> RepositoryCodeSearch:
        """Search code inside one repository accessible to the selected account."""
        return client_factory(account_id).search_code(repository, query, per_page, page)


def _register_pull_evidence(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub reviewer list pull requests", annotations=read_annotations)
    def github_reviewer_list_pull_requests(
        account_id: str,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> PullList:
        """List pull requests available for review."""
        return client_factory(account_id).list_pull_requests(repository, state, per_page, page)

    mcp.tool(title="GitHub reviewer get pull request", annotations=read_annotations)(
        _pull_request_reader(
            client_factory,
            name="github_reviewer_get_pull_request",
        )
    )

    @mcp.tool(title="GitHub reviewer pull files", annotations=read_annotations)
    def github_reviewer_pull_files(
        account_id: str,
        repository: str,
        number: int,
    ) -> PullFiles:
        """Read changed files and patches for a pull request."""
        return client_factory(account_id).list_pull_files(repository, number)

    @mcp.tool(title="GitHub reviewer list reviews", annotations=read_annotations)
    def github_reviewer_list_reviews(
        account_id: str,
        repository: str,
        number: int,
    ) -> PullReviews:
        """List existing review submissions."""
        return client_factory(account_id).list_reviews(repository, number)

    @mcp.tool(title="GitHub reviewer list review threads", annotations=read_annotations)
    def github_reviewer_list_review_threads(
        account_id: str,
        repository: str,
        number: int,
    ) -> ReviewThreads:
        """List inline review threads and resolution state."""
        return client_factory(account_id).list_review_threads(repository, number)

    @mcp.tool(title="GitHub reviewer inline comments", annotations=read_annotations)
    def github_reviewer_list_review_comments(
        account_id: str,
        repository: str,
        number: int,
    ) -> ReviewComments:
        """List flat inline review comments for a pull request."""
        return client_factory(account_id).list_review_comments(repository, number)

    @mcp.tool(title="GitHub reviewer conversation comments", annotations=read_annotations)
    def github_reviewer_list_conversation_comments(
        account_id: str,
        repository: str,
        number: int,
        page: int = 1,
        per_page: int = 100,
    ) -> ConversationComments:
        """List one page of top-level issue/PR comments."""
        return client_factory(account_id).list_conversation_comments(
            repository, number, page, per_page
        )

    @mcp.tool(
        title="GitHub reviewer check runs",
        annotations=read_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_reviewer_check_runs(account_id: str, repository: str, ref: str) -> CallToolResult:
        """Read CI check-runs for a commit/ref."""
        return review_result(client_factory(account_id).check_runs(repository, ref))

    @mcp.tool(
        title="GitHub reviewer required checks",
        annotations=read_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_reviewer_required_checks(
        account_id: str,
        repository: str,
        ref: str,
    ) -> CallToolResult:
        """Verify configured required checks before approval."""
        return review_result(client_factory(account_id).assert_required_checks(repository, ref))

    @mcp.tool(
        title="GitHub reviewer required reviews",
        annotations=read_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_reviewer_required_reviews(
        account_id: str,
        repository: str,
        number: int,
    ) -> CallToolResult:
        """Verify configured approvals against the current pull-request head."""
        return review_result(client_factory(account_id).assert_required_reviews(repository, number))


def _register_workflow_evidence(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub reviewer workflow runs", annotations=read_annotations)
    def github_reviewer_workflow_runs(
        account_id: str,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> WorkflowRunList:
        """List Actions workflow runs for review diagnostics."""
        return client_factory(account_id).list_workflow_runs(
            repository,
            branch,
            status,
            per_page,
            page,
        )

    @mcp.tool(title="GitHub reviewer workflow jobs", annotations=read_annotations)
    def github_reviewer_workflow_jobs(
        account_id: str,
        repository: str,
        run_id: int,
    ) -> WorkflowJobList:
        """List jobs for one Actions workflow run."""
        return client_factory(account_id).list_workflow_jobs(repository, run_id)


def _register_review_actions(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub reviewer rich review", annotations=write_annotations)
    def github_reviewer_create_review(
        account_id: str,
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: list[ReviewComment] | None = None,
        commit_id: str | None = None,
    ) -> ReviewCreation:
        """Submit COMMENT, APPROVE, or REQUEST_CHANGES with optional inline comments."""
        return client_factory(account_id).create_review_with_comments(
            repository,
            number,
            event,
            body,
            comments,
            commit_id,
        )

    @mcp.tool(
        title="GitHub reviewer merge pull request",
        annotations=write_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_reviewer_merge_pull_request(
        account_id: str,
        repository: str,
        number: int,
        delete_source_branch_after_merge: bool,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
        expected_head_sha: str | None = None,
    ) -> CallToolResult:
        """Merge a same-repository PR after validating its current head and required checks."""
        return merge_result(
            client_factory(account_id).merge_pull_request(
                repository,
                number,
                delete_source_branch_after_merge,
                merge_method,
                commit_title,
                commit_message,
                expected_head_sha,
            )
        )

    @mcp.tool(title="GitHub reviewer update review comment", annotations=write_annotations)
    def github_reviewer_update_review_comment(
        account_id: str,
        repository: str,
        comment_id: int,
        body: str,
    ) -> ReviewCommentUpdated:
        """Replace the body of an inline review comment."""
        return client_factory(account_id).update_review_comment(
            repository,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub reviewer reply to comment", annotations=write_annotations)
    def github_reviewer_reply_to_review_comment(
        account_id: str,
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> ReviewCommentReply:
        """Reply inside an inline review thread."""
        return client_factory(account_id).reply_to_review_comment(
            repository,
            number,
            comment_id,
            body,
        )

    @mcp.tool(title="GitHub reviewer set thread state", annotations=write_annotations)
    def github_reviewer_set_review_thread_resolved(
        account_id: str,
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> ReviewThreadResolution:
        """Resolve or reopen one review thread."""
        return client_factory(account_id).set_review_thread_resolved(
            repository,
            thread_id,
            resolved,
        )
