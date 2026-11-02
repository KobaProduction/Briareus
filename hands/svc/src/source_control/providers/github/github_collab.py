from __future__ import annotations

from pydantic import ValidationError

from .application.review_gates import RequiredReviewsReceipt, RequireReviews
from .collaboration_views import (
    BranchAlreadyMerged,
    BranchMerged,
    PullReady,
    RemovedReviewers,
    RequestedReviewers,
    ReviewCommentReply,
    ReviewCommentUpdated,
    ReviewThreadResolution,
    ReviewThreads,
)
from .domain.review_gates import ReviewGateError
from .domain.review_threads import ReviewThread, ThreadComment
from .github_agent import GitHubAgentError
from .github_review import GitHubReviewClient
from .infrastructure.review_gates import GitHubReviewGates
from .infrastructure.schemas.collaboration import (
    BranchMergeRequest,
    CommentBody,
    ConversationRecord,
    PullRequestRecord,
    ReviewCommentReplyRecord,
    ReviewerRecords,
    ReviewersRequest,
)
from .infrastructure.schemas.graphql import (
    GraphQLReply,
    GraphQLRequest,
    PullNodeInput,
    PullNodeVariables,
    ReadyPullData,
    ThreadQueryData,
    ThreadQueryVariables,
    ThreadResolutionData,
    ThreadResolutionInput,
    ThreadResolutionVariables,
)
from .infrastructure.schemas.repository import GitObjectId
from .pulls import GitHubPullClient


class GitHubCollabClient(GitHubReviewClient, GitHubPullClient):
    """Collaboration operations for branch/PR review loops."""

    independent_review_gate: bool = True

    def assert_required_reviews(self, repository: str, number: int) -> RequiredReviewsReceipt:
        try:
            return RequireReviews(GitHubReviewGates(self)).execute(
                repository, number, tuple(self.required_reviewers)
            )
        except ReviewGateError as exc:
            raise GitHubAgentError(str(exc)) from exc

    def merge_branch(
        self,
        repository: str,
        base: str,
        head: str,
        commit_message: str | None = None,
    ) -> BranchMerged | BranchAlreadyMerged:
        repository = self._assert_allowed(repository)
        base = self._assert_mutable_branch(base)
        response = self._repo_transport(
            repository,
            "POST",
            f"/repos/{repository}/merges",
            payload=BranchMergeRequest(base=base, head=head, commit_message=commit_message or None),
            allowed_errors={204, 409},
        )
        if response.status == 204:
            return BranchAlreadyMerged(
                repository=repository,
                base=base,
                head=head,
                status=response.status,
                merged=False,
                message="base already contains head",
            )
        if response.status == 409:
            raise GitHubAgentError("branch merge conflict")
        try:
            result = GitObjectId.model_validate_json(response.body)
        except ValidationError as exc:
            raise GitHubAgentError("unexpected branch merge response") from exc
        return BranchMerged(
            repository=repository,
            base=base,
            head=head,
            status=response.status,
            merged=True,
            commit_sha=result.sha,
        )

    def request_reviewers(
        self,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> RequestedReviewers:
        repository = self._assert_allowed(repository)
        if not reviewers and not team_reviewers:
            raise GitHubAgentError("at least one reviewer or team reviewer is required")
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/requested_reviewers",
            response_type=ReviewerRecords,
            payload=ReviewersRequest(
                reviewers=reviewers or None, team_reviewers=team_reviewers or None
            ),
        ).data
        return RequestedReviewers(
            repository=repository,
            number=number,
            reviewers=[user.login or "" for user in result.requested_reviewers],
            teams=[team.slug or "" for team in result.requested_teams],
        )

    def remove_requested_reviewers(
        self,
        repository: str,
        number: int,
        reviewers: list[str] | None = None,
        team_reviewers: list[str] | None = None,
    ) -> RemovedReviewers:
        repository = self._assert_allowed(repository)
        if not reviewers and not team_reviewers:
            raise GitHubAgentError("at least one reviewer or team reviewer is required")
        self._repo_ack(
            repository,
            "DELETE",
            f"/repos/{repository}/pulls/{number}/requested_reviewers",
            payload=ReviewersRequest(
                reviewers=reviewers or None, team_reviewers=team_reviewers or None
            ),
        )
        return RemovedReviewers(repository=repository, number=number, removed=True)

    def update_review_comment(
        self,
        repository: str,
        comment_id: int,
        body: str,
    ) -> ReviewCommentUpdated:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/comments/{comment_id}",
            response_type=ConversationRecord,
            payload=CommentBody(body=body),
        ).data
        return ReviewCommentUpdated(
            repository=repository,
            comment_id=result.id,
            body=result.body or "",
            html_url=result.html_url,
        )

    def reply_to_review_comment(
        self,
        repository: str,
        number: int,
        comment_id: int,
        body: str,
    ) -> ReviewCommentReply:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/comments/{comment_id}/replies",
            response_type=ReviewCommentReplyRecord,
            payload=CommentBody(body=body),
        ).data
        return ReviewCommentReply(
            repository=repository,
            number=number,
            comment_id=result.id,
            in_reply_to_id=result.in_reply_to_id
            if result.in_reply_to_id is not None
            else comment_id,
            html_url=result.html_url,
        )

    def list_review_threads(
        self,
        repository: str,
        number: int,
    ) -> ReviewThreads:
        repository = self._assert_allowed(repository)
        owner, name = repository.split("/", 1)
        query = """
        query PullReviewThreads($owner: String!, $name: String!, $number: Int!) {
          repository(owner: $owner, name: $name) {
            pullRequest(number: $number) {
              reviewThreads(first: 100) {
                nodes {
                  id
                  isResolved
                  isOutdated
                  path
                  line
                  startLine
                  comments(first: 100) {
                    nodes {
                      id
                      databaseId
                      body
                      author { login }
                      createdAt
                      url
                    }
                  }
                }
              }
            }
          }
        }
        """
        data = self._graphql(
            repository,
            GraphQLRequest[ThreadQueryVariables](
                query=query, variables=ThreadQueryVariables(owner=owner, name=name, number=number)
            ),
            GraphQLReply[ThreadQueryData],
        )
        threads = tuple(
            ReviewThread(
                id=thread.id,
                resolved=thread.is_resolved,
                outdated=thread.is_outdated,
                path=thread.path,
                line=thread.line,
                start_line=thread.start_line,
                comments=tuple(
                    ThreadComment(
                        id=comment.id,
                        database_id=comment.database_id,
                        author=comment.author.login or "" if comment.author else "",
                        body=comment.body,
                        created_at=comment.created_at,
                        url=comment.url,
                    )
                    for comment in thread.comments.nodes
                ),
            )
            for thread in data.repository.pull_request.review_threads.nodes
        )
        return ReviewThreads(repository=repository, number=number, threads=threads)

    def set_review_thread_resolved(
        self,
        repository: str,
        thread_id: str,
        resolved: bool,
    ) -> ReviewThreadResolution:
        repository = self._assert_allowed(repository)
        if resolved:
            field = "resolveReviewThread"
            input_type = "ResolveReviewThreadInput!"
        else:
            field = "unresolveReviewThread"
            input_type = "UnresolveReviewThreadInput!"
        mutation = f"""
        mutation ReviewThreadState($input: {input_type}) {{
          {field}(input: $input) {{
            thread {{ id isResolved }}
          }}
        }}
        """
        data = self._graphql(
            repository,
            GraphQLRequest[ThreadResolutionVariables](
                query=mutation,
                variables=ThreadResolutionVariables(
                    input=ThreadResolutionInput(thread_id=thread_id)
                ),
            ),
            GraphQLReply[ThreadResolutionData],
        )
        payload = data.resolve_review_thread if resolved else data.unresolve_review_thread
        if payload is None:
            raise GitHubAgentError("GraphQL review thread mutation returned no thread")
        return ReviewThreadResolution(
            repository=repository, thread_id=payload.thread.id, resolved=payload.thread.is_resolved
        )

    def mark_pull_ready_for_review(
        self,
        repository: str,
        number: int,
    ) -> PullReady:
        repository = self._assert_allowed(repository)
        pull = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
            response_type=PullRequestRecord,
        ).data
        node_id = pull.node_id
        if not node_id:
            raise GitHubAgentError("pull request has no GraphQL node id")
        mutation = """
        mutation MarkReady($input: MarkPullRequestReadyForReviewInput!) {
          markPullRequestReadyForReview(input: $input) {
            pullRequest { number isDraft }
          }
        }
        """
        data = self._graphql(
            repository,
            GraphQLRequest[PullNodeVariables](
                query=mutation,
                variables=PullNodeVariables(input=PullNodeInput(pull_request_id=node_id)),
            ),
            GraphQLReply[ReadyPullData],
        )
        result = data.mark_pull_request_ready_for_review.pull_request
        return PullReady(repository=repository, number=result.number, draft=result.is_draft)
