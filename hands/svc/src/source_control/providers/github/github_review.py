from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ValidationError

from .base import GitHubRepositoryClientBase
from .comment_views import ConversationComment, InlineReviewComment
from .domain.mutations import ReviewEvent
from .execution_views import (
    ConversationComments,
    ReviewBranchUpdate,
    ReviewComments,
    ReviewCreation,
)
from .github_agent import GitHubAgentError
from .infrastructure.schemas.collaboration import (
    ConversationRecords,
    PullRequestRecord,
    ReviewCommentRecords,
    ReviewCreate,
    ReviewRecord,
)
from .infrastructure.schemas.graphql import (
    BranchUpdateData,
    GraphQLReply,
    GraphQLRequest,
    UpdateBranchInput,
    UpdateBranchVariables,
)
from .infrastructure.schemas.pagination import PageQuery
from .models import ReviewComment


class GitHubReviewClient(GitHubRepositoryClientBase):
    """Adds GraphQL rebase/update and richer PR review operations."""

    def _graphql[V: BaseModel, T: BaseModel](
        self,
        repository: str,
        request: GraphQLRequest[V],
        response_type: type[GraphQLReply[T]],
    ) -> T:
        repository = self._assert_allowed(repository)
        token = self._installation_token(repository)
        response = self._request_transport(
            "POST",
            "https://api.github.com/graphql",
            token=token,
            payload=request,
            auth_mode="user_token" if self.token else "installation",
        )
        try:
            result = response_type.model_validate_json(response.body)
        except ValidationError as exc:
            raise GitHubAgentError("GitHub returned an invalid GraphQL response schema") from exc
        if result.errors:
            raise GitHubAgentError(
                "GitHub GraphQL error: " + "; ".join(error.message for error in result.errors)
            )
        if result.data is None:
            raise GitHubAgentError("GitHub GraphQL response has no data")
        return result.data

    def update_pull_branch_graphql(
        self,
        repository: str,
        number: int,
        method: str = "MERGE",
        expected_head_sha: str | None = None,
    ) -> ReviewBranchUpdate:
        repository = self._assert_allowed(repository)
        method = method.upper()
        if method not in {"MERGE", "REBASE"}:
            raise GitHubAgentError("method must be MERGE or REBASE")

        pull = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
            response_type=PullRequestRecord,
        ).data
        node_id = pull.node_id
        if pull.head.repo is None or pull.head.repo.full_name.casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request update is disabled")
        if not node_id:
            raise GitHubAgentError("pull request has no GraphQL node id")
        current_head = pull.head.sha
        if expected_head_sha and current_head != expected_head_sha:
            raise GitHubAgentError(
                f"pull request head changed: expected {expected_head_sha}, found {current_head}"
            )

        mutation = """
        mutation UpdatePullRequestBranch($input: UpdatePullRequestBranchInput!) {
          updatePullRequestBranch(input: $input) {
            pullRequest {
              number
              headRefName
              headRefOid
              baseRefName
              mergeable
            }
          }
        }
        """
        data = self._graphql(
            repository,
            GraphQLRequest[UpdateBranchVariables](
                query=mutation,
                variables=UpdateBranchVariables(
                    input=UpdateBranchInput(
                        pull_request_id=node_id,
                        update_method=method,
                        expected_head_oid=expected_head_sha or None,
                    )
                ),
            ),
            GraphQLReply[BranchUpdateData],
        )
        result = data.update_pull_request_branch.pull_request
        return ReviewBranchUpdate(
            repository=repository,
            number=result.number,
            head=result.head_ref_name,
            head_sha=result.head_ref_oid,
            base=result.base_ref_name,
            mergeable=result.mergeable,
            method=method,
        )

    def create_review_with_comments(
        self,
        repository: str,
        number: int,
        event: str,
        body: str,
        comments: Sequence[ReviewComment] | None = None,
        commit_id: str | None = None,
    ) -> ReviewCreation:
        repository = self._assert_allowed(repository)
        try:
            review_event = ReviewEvent(event.upper())
        except ValueError as exc:
            raise GitHubAgentError("event must be APPROVE, REQUEST_CHANGES, or COMMENT") from exc
        payload = ReviewCreate(
            event=review_event,
            body=body,
            commit_id=commit_id or None,
            comments=list(comments) if comments else None,
        )
        result = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/reviews",
            response_type=ReviewRecord,
            payload=payload,
        ).data
        return ReviewCreation(
            repository=repository,
            number=number,
            review_id=result.id,
            state=result.state,
            commit_id=result.commit_id or "",
        )

    def list_conversation_comments(
        self,
        repository: str,
        number: int,
        page: int = 1,
        per_page: int = 100,
    ) -> ConversationComments:
        repository = self._assert_allowed(repository)
        if type(page) is not int or page < 1:
            raise GitHubAgentError("page must be a positive integer")
        if type(per_page) is not int or not 1 <= per_page <= 100:
            raise GitHubAgentError("per_page must be between 1 and 100")
        response = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/issues/{number}/comments",
            response_type=ConversationRecords,
            query=PageQuery(page=page, per_page=per_page),
        )
        comments = [
            ConversationComment(
                id=item.id,
                user=item.user.login or "" if item.user else "",
                body=item.body or "",
                created_at=item.created_at,
                updated_at=item.updated_at,
                html_url=item.html_url,
            )
            for item in response.data.root
        ]
        next_page = response.pagination.next_after(page)
        return ConversationComments(
            repository=repository,
            number=number,
            comments=comments,
            page=page,
            per_page=per_page,
            returned_count=len(comments),
            has_next_page=next_page is not None,
            next_page=next_page,
        )

    def list_review_comments(
        self,
        repository: str,
        number: int,
    ) -> ReviewComments:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/comments?per_page=100",
            response_type=ReviewCommentRecords,
        ).data.root
        comments = [
            InlineReviewComment(
                id=item.id,
                user=item.user.login or "" if item.user else "",
                path=item.path,
                line=item.line,
                side=item.side,
                body=item.body or "",
                commit_id=item.commit_id,
                html_url=item.html_url,
            )
            for item in result
        ]
        return ReviewComments(
            repository=repository,
            number=number,
            comments=comments,
        )
