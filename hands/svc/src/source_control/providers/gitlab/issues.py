from __future__ import annotations

from .activity_views import (
    IssueList,
    IssueNote,
    IssueResponse,
)
from .api import GitLabApiClient
from .errors import GitLabError
from .infrastructure.schemas.activity import (
    GitLabIssue,
    GitLabNote,
    IssueCreate,
    IssueQuery,
    IssueRecords,
    IssueUpdate,
    NoteCreate,
)


class GitLabIssueClient(GitLabApiClient):
    def list_issues(
        self,
        project: str | int,
        state: str = "opened",
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> IssueList:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/issues",
            response_type=IssueRecords,
            query=IssueQuery(
                state=state or None, search=search or None, page=page, per_page=per_page
            ),
        )
        return IssueList(
            profile_id=self.profile.profile_id,
            project=str(project),
            issues=response.data.root,
            next_page=response.pagination.next_page,
        )

    def get_issue(self, project: str | int, iid: int) -> IssueResponse:
        selector = self.project_selector(project)
        data = self.request_model(
            "GET", f"/projects/{selector}/issues/{iid}", response_type=GitLabIssue
        ).data
        return IssueResponse(profile_id=self.profile.profile_id, project=str(project), issue=data)

    def create_issue(
        self,
        project: str | int,
        title: str,
        description: str = "",
        labels: list[str] | None = None,
    ) -> IssueResponse:
        selector = self.project_selector(project)
        payload = IssueCreate(
            title=title, description=description, labels=",".join(labels) if labels else None
        )
        data = self.request_model(
            "POST",
            f"/projects/{selector}/issues",
            payload=payload,
            response_type=GitLabIssue,
        ).data
        return IssueResponse(profile_id=self.profile.profile_id, project=str(project), issue=data)

    def update_issue(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        labels: list[str] | None = None,
    ) -> IssueResponse:
        selector = self.project_selector(project)
        if title is None and description is None and state_event is None and labels is None:
            raise GitLabError("at least one issue field must be supplied")
        payload = IssueUpdate(
            title=title,
            description=description,
            state_event=state_event,
            labels=",".join(labels) if labels is not None else None,
        )
        data = self.request_model(
            "PUT",
            f"/projects/{selector}/issues/{iid}",
            payload=payload,
            response_type=GitLabIssue,
        ).data
        return IssueResponse(profile_id=self.profile.profile_id, project=str(project), issue=data)

    def add_issue_note(
        self,
        project: str | int,
        iid: int,
        body: str,
    ) -> IssueNote:
        selector = self.project_selector(project)
        data = self.request_model(
            "POST",
            f"/projects/{selector}/issues/{iid}/notes",
            payload=NoteCreate(body=body),
            response_type=GitLabNote,
        ).data
        return IssueNote(profile_id=self.profile.profile_id, project=str(project), note=data)
