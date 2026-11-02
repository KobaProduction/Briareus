from __future__ import annotations

from .base import GitHubRepositoryClientBase
from .collaboration_views import (
    CommentCreated,
    CompactIssue,
    IssueList,
    IssueResponse,
)
from .domain.mutations import IssueChange, MutationError
from .github_agent import GitHubAgentError
from .infrastructure.schemas.collaboration import (
    CommentBody,
    ConversationRecord,
    DiscussionQuery,
    IssueCreate,
    IssueRecord,
    IssueRecords,
    IssueUpdate,
)


class GitHubIssueClient(GitHubRepositoryClientBase):
    def list_issues(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> IssueList:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
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
        issues = []
        for item in result:
            if item.is_pull_request:
                continue
            issues.append(self._compact_issue(item))
        return IssueList(repository=repository, issues=issues, page=page)

    @staticmethod
    def _compact_issue(item: IssueRecord) -> CompactIssue:
        return CompactIssue(
            number=item.number,
            title=item.title,
            state=item.state,
            body=item.body or "",
            html_url=item.html_url,
        )

    def get_issue(self, repository: str, number: int) -> IssueResponse:
        repository = self._assert_allowed(repository)
        response = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/issues/{number}",
            response_type=IssueRecord,
        )
        result = response.data
        if result.is_pull_request:
            raise GitHubAgentError("number does not refer to an issue")
        return IssueResponse(repository=repository, issue=self._compact_issue(result))

    def create_issue(
        self,
        repository: str,
        title: str,
        body: str = "",
        labels: list[str] | None = None,
    ) -> IssueResponse:
        repository = self._assert_allowed(repository)
        payload = IssueCreate(title=title, body=body, labels=labels)
        response = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/issues",
            payload=payload,
            response_type=IssueRecord,
        )
        result = response.data
        return IssueResponse(repository=repository, issue=self._compact_issue(result))

    def update_issue(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        labels: list[str] | None = None,
    ) -> IssueResponse:
        repository = self._assert_allowed(repository)
        try:
            IssueChange(
                title, body, state, tuple(labels) if labels is not None else None
            ).require_valid()
        except MutationError as exc:
            raise GitHubAgentError(str(exc)) from exc
        payload = IssueUpdate(title=title, body=body, state=state, labels=labels)
        response = self._repo_model(
            repository,
            "PATCH",
            f"/repos/{repository}/issues/{number}",
            payload=payload,
            response_type=IssueRecord,
        )
        result = response.data
        return IssueResponse(repository=repository, issue=self._compact_issue(result))

    def add_issue_comment(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> CommentCreated:
        repository = self._assert_allowed(repository)
        response = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            payload=CommentBody(body=body),
            response_type=ConversationRecord,
        )
        result = response.data
        return CommentCreated(
            repository=repository,
            number=number,
            comment_id=result.id,
            html_url=result.html_url,
        )
