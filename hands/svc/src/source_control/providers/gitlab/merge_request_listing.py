"""GitLab list projection with selected-root nominal MCP page constructors."""

from __future__ import annotations

from .api import GitLabApiClient
from .domain.mutations import require_note_body
from .infrastructure.schemas.activity import GitLabNote, NoteCreate
from .infrastructure.schemas.merge_requests import (
    MergeRequest,
    MergeRequestDetailsQuery,
    MergeRequestQuery,
    MergeRequestRecords,
)
from .merge_receipts import MergeRequestNoteResult, MergeRequestPage, MergeRequestResult


class MergeRequestListing(GitLabApiClient):
    def list_merge_requests(
        self,
        project: str | int,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> MergeRequestPage:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/merge_requests",
            response_type=MergeRequestRecords,
            query=MergeRequestQuery(
                state=state or None,
                source_branch=source_branch or None,
                target_branch=target_branch or None,
                page=page,
                per_page=per_page,
            ),
        )
        return MergeRequestPage(
            profile_id=self.profile.profile_id,
            project=str(project),
            merge_requests=response.data.root,
            next_page=response.pagination.next_page,
        )

    def get_merge_request(self, project: str | int, iid: int) -> MergeRequestResult:
        selector = self.project_selector(project)
        data = self.request_model(
            "GET",
            f"/projects/{selector}/merge_requests/{iid}",
            response_type=MergeRequest,
            query=MergeRequestDetailsQuery(),
        ).data
        return MergeRequestResult(
            profile_id=self.profile.profile_id, project=str(project), merge_request=data
        )

    def add_merge_request_note(
        self,
        project: str | int,
        iid: int,
        body: str,
    ) -> MergeRequestNoteResult:
        selector = self.project_selector(project)
        require_note_body(body)
        data = self.request_model(
            "POST",
            f"/projects/{selector}/merge_requests/{iid}/notes",
            payload=NoteCreate(body=body),
            response_type=GitLabNote,
        ).data
        return MergeRequestNoteResult(
            profile_id=self.profile.profile_id, project=str(project), iid=iid, note=data
        )
