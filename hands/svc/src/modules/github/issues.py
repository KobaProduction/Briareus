from __future__ import annotations

from source_control.providers.github.issues import GitHubIssueClient as _SharedGitHubIssueClient

from .base import GitHubRepositoryClientBase
from .collaboration_views import CommentCreated as CommentCreated
from .collaboration_views import CompactIssue as CompactIssue
from .collaboration_views import IssueCommentDeleted, IssueCommentUpdated, IssuePage
from .collaboration_views import IssueResponse as IssueResponse
from .domain.mutations import IssueChange as IssueChange
from .domain.mutations import MutationError as MutationError
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.collaboration import CommentBody as CommentBody
from .infrastructure.schemas.collaboration import ConversationRecord as ConversationRecord
from .infrastructure.schemas.collaboration import DiscussionQuery as DiscussionQuery
from .infrastructure.schemas.collaboration import IssueCreate as IssueCreate
from .infrastructure.schemas.collaboration import IssueRecord as IssueRecord
from .infrastructure.schemas.collaboration import IssueRecords as IssueRecords
from .infrastructure.schemas.collaboration import IssueUpdate as IssueUpdate


class GitHubIssueClient(_SharedGitHubIssueClient, GitHubRepositoryClientBase):
    def list_issues(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> IssuePage:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
        page, per_page = max(1, page), max(1, min(per_page, 100))
        response = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/issues",
            response_type=IssueRecords,
            query=DiscussionQuery(
                state=state, per_page=max(1, min(per_page, 100)), page=max(1, page)
            ),
        )
        result = response.data.root
        # GitHub pages include PRs. Derive continuation from Link, never the
        # filtered issue count (an entire page can consist of PRs).
        next_page = response.pagination.next_after(page)
        issues = []
        for item in result:
            if item.is_pull_request:
                continue
            issues.append(self._compact_issue(item))
        return IssuePage(
            repository=repository,
            issues=issues,
            page=page,
            per_page=per_page,
            count=len(issues),
            raw_count=len(result),
            has_next=next_page is not None,
            next_page=next_page,
        )

    def update_issue_comment(
        self, repository: str, comment_id: int, body: str
    ) -> IssueCommentUpdated:
        """Edit a top-level issue/PR conversation comment using GitHub permissions."""
        repository = self._assert_allowed(repository)
        if type(comment_id) is not int or comment_id <= 0:
            raise GitHubAgentError("comment_id must be a positive integer")
        candidate_body: object = body
        if not isinstance(candidate_body, str) or not candidate_body.strip():
            raise GitHubAgentError("comment body must not be empty")
        response = self._repo_model(
            repository,
            "PATCH",
            f"/repos/{repository}/issues/comments/{comment_id}",
            payload=CommentBody(body=body),
            response_type=ConversationRecord,
        )
        result = response.data
        return IssueCommentUpdated(
            repository=repository,
            comment_id=result.id,
            html_url=result.html_url,
            body=result.body or "",
            updated=True,
        )

    def delete_issue_comment(
        self,
        repository: str,
        comment_id: int,
        confirm: bool = False,
    ) -> IssueCommentDeleted:
        """Permanently delete a conversation comment, requiring explicit confirmation."""
        repository = self._assert_allowed(repository)
        if type(comment_id) is not int or comment_id <= 0:
            raise GitHubAgentError("comment_id must be a positive integer")
        if confirm is not True:
            raise GitHubAgentError("deleting a comment requires confirm=true")
        self._repo_ack(
            repository,
            "DELETE",
            f"/repos/{repository}/issues/comments/{comment_id}",
        )
        return IssueCommentDeleted(repository=repository, comment_id=comment_id, deleted=True)
