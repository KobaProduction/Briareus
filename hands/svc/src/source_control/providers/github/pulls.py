from __future__ import annotations

from service_runtime.merge_policy import branch_choice, with_branch_choice

from .application.merge import MergeCommand, MergePullRequest, MergeReceipt
from .application.review_gates import CheckRunsReceipt, RequireChecks, RequiredChecksReceipt
from .base import GitHubRepositoryClientBase
from .collaboration_views import (
    CommentCreated,
    CompactPull,
    PullBranchUpdated,
    PullDetails,
    PullDetailsResponse,
    PullFiles,
    PullList,
    PullResponse,
    PullReviews,
    ReviewSubmitted,
)
from .comment_views import PullReviewSummary
from .domain.merge import MergeError
from .domain.mutations import MutationError, PullChange, ReviewEvent
from .domain.review_gates import ReviewGateError
from .github_agent import GitHubAgentError
from .infrastructure.merge import GitHubMerge
from .infrastructure.review_gates import GitHubReviewGates
from .infrastructure.schemas.collaboration import (
    CommentBody,
    ConversationRecord,
    DiscussionQuery,
    PullBranchUpdate,
    PullBranchUpdateResult,
    PullCreate,
    PullRecords,
    PullRequestRecord,
    PullUpdate,
    ReviewCreate,
    ReviewRecord,
    ReviewRecords,
)
from .infrastructure.schemas.repository import CommitFiles


class GitHubPullClient(GitHubRepositoryClientBase):
    independent_review_gate: bool = False

    def list_pull_requests(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> PullList:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls",
            response_type=PullRecords,
            query=DiscussionQuery(
                state=state, per_page=max(1, min(per_page, 100)), page=max(1, page)
            ),
        ).data.root
        return PullList(
            repository=repository,
            pull_requests=[self._compact_pull(item) for item in result],
            page=page,
        )

    @staticmethod
    def _compact_pull(item: PullRequestRecord) -> CompactPull:
        return CompactPull(
            number=item.number,
            title=item.title,
            state=item.state,
            draft=item.draft,
            head=item.head.ref,
            head_sha=item.head.sha,
            base=item.base.ref,
            merged=item.merged,
            html_url=item.html_url,
            delete_source_branch_after_merge=branch_choice(item.body or ""),
        )

    def get_pull_request(self, repository: str, number: int) -> PullDetailsResponse:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
            response_type=PullRequestRecord,
        ).data
        compact = self._compact_pull(result)
        details = PullDetails(
            number=compact.number,
            title=compact.title,
            state=compact.state,
            draft=compact.draft,
            head=compact.head,
            head_sha=compact.head_sha,
            base=compact.base,
            merged=compact.merged,
            html_url=compact.html_url,
            delete_source_branch_after_merge=compact.delete_source_branch_after_merge,
            body=result.body or "",
            mergeable=result.mergeable,
            mergeable_state=result.mergeable_state or "",
        )
        return PullDetailsResponse(repository=repository, pull_request=details)

    def create_pull_request(
        self,
        repository: str,
        title: str,
        head: str,
        base: str,
        delete_source_branch_after_merge: bool,
        body: str = "",
        draft: bool = False,
    ) -> PullResponse:
        body = with_branch_choice(body, delete_source_branch_after_merge)
        repository = self._assert_allowed(repository)
        if ":" in head or ":" in base:
            raise GitHubAgentError("cross-repository pull requests are disabled")
        if head == base:
            raise GitHubAgentError("pull request head and base must differ")
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/pulls",
            response_type=PullRequestRecord,
            payload=PullCreate(title=title, head=head, base=base, body=body, draft=draft),
        ).data
        return PullResponse(repository=repository, pull_request=self._compact_pull(result))

    def update_pull_request(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> PullResponse:
        repository = self._assert_allowed(repository)
        try:
            PullChange(title, body, state, base).require_valid()
        except MutationError as exc:
            raise GitHubAgentError(str(exc)) from exc
        if body is not None:
            current = self._repo_model(
                repository,
                "GET",
                f"/repos/{repository}/pulls/{number}",
                response_type=PullRequestRecord,
            ).data
            choice = branch_choice(current.body or "")
            body = with_branch_choice(body, choice) if choice is not None else body
        result = self._repo_model(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/{number}",
            response_type=PullRequestRecord,
            payload=PullUpdate(title=title, body=body, state=state, base=base),
        ).data
        return PullResponse(repository=repository, pull_request=self._compact_pull(result))

    def list_pull_files(self, repository: str, number: int) -> PullFiles:
        repository = self._assert_allowed(repository)
        files = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/files?per_page=100",
            response_type=CommitFiles,
        ).data.root
        return PullFiles(repository=repository, number=number, files=files)

    def add_pull_comment(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> CommentCreated:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            response_type=ConversationRecord,
            payload=CommentBody(body=body),
        ).data
        return CommentCreated(
            repository=repository, number=number, comment_id=result.id, html_url=result.html_url
        )

    def list_reviews(self, repository: str, number: int) -> PullReviews:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
            response_type=ReviewRecords,
        ).data.root
        reviews = [
            PullReviewSummary(
                id=item.id,
                user=item.user.login or "" if item.user else "",
                state=item.state,
                body=item.body or "",
                submitted_at=item.submitted_at or "",
            )
            for item in result
        ]
        return PullReviews(
            repository=repository,
            number=number,
            reviews=reviews,
        )

    def create_review(
        self,
        repository: str,
        number: int,
        event: str,
        body: str,
    ) -> ReviewSubmitted:
        repository = self._assert_allowed(repository)
        try:
            review_event = ReviewEvent(event.upper())
        except ValueError as exc:
            raise GitHubAgentError("event must be APPROVE, REQUEST_CHANGES, or COMMENT") from exc
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/reviews",
            response_type=ReviewRecord,
            payload=ReviewCreate(event=review_event, body=body),
        ).data
        return ReviewSubmitted(
            repository=repository,
            number=number,
            review_id=result.id,
            state=result.state,
        )

    def update_pull_branch(
        self,
        repository: str,
        number: int,
        expected_head_sha: str | None = None,
    ) -> PullBranchUpdated:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/update-branch",
            response_type=PullBranchUpdateResult,
            payload=PullBranchUpdate(expected_head_sha=expected_head_sha or None),
        ).data
        return PullBranchUpdated(repository=repository, number=number, result=result)

    def check_runs(self, repository: str, ref: str) -> CheckRunsReceipt:
        return GitHubReviewGates(self).checks(repository, ref)

    def assert_required_checks(self, repository: str, ref: str) -> RequiredChecksReceipt:
        try:
            return RequireChecks(GitHubReviewGates(self)).execute(
                repository, ref, tuple(self.required_checks)
            )
        except ReviewGateError as exc:
            raise GitHubAgentError(str(exc)) from exc

    def merge_pull_request(
        self,
        repository: str,
        number: int,
        delete_source_branch_after_merge: bool,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
        expected_head_sha: str | None = None,
    ) -> MergeReceipt:
        command = MergeCommand(
            repository,
            number,
            delete_source_branch_after_merge,
            merge_method,
            commit_title,
            commit_message,
            expected_head_sha,
        )
        try:
            return MergePullRequest(GitHubMerge(self, self.independent_review_gate)).execute(
                command
            )
        except MergeError as exc:
            raise GitHubAgentError(str(exc)) from exc
