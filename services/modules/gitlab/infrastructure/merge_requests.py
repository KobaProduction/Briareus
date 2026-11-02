from __future__ import annotations

from modules.gitlab.api import GitLabApiClient as GitLabApiClient
from modules.gitlab.domain.mutations import MergeRequestUpdate as MergeRequestUpdate
from modules.gitlab.domain.mutations import merge_request_title as merge_request_title
from modules.gitlab.domain.mutations import require_note_body as require_note_body
from modules.gitlab.infrastructure.schemas.activity import GitLabNote as GitLabNote
from modules.gitlab.infrastructure.schemas.activity import NoteCreate as NoteCreate
from modules.gitlab.infrastructure.schemas.merge_requests import MergeRequest as MergeRequest
from modules.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestAccept as MergeRequestAccept,
)
from modules.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestCreate as MergeRequestCreate,
)
from modules.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestDetailsQuery as MergeRequestDetailsQuery,
)
from modules.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestQuery as MergeRequestQuery,
)
from modules.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestRecords as MergeRequestRecords,
)
from modules.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequestUpdate as MergeRequestUpdateBody,
)
from modules.gitlab.infrastructure.schemas.pagination import PageQuery as PageQuery
from modules.gitlab.infrastructure.schemas.repository import DiffRecords as DiffRecords
from source_control.providers.gitlab.merge_receipts import MergeRequestDiffPage, MergeRequestResult
from source_control.providers.gitlab.merge_request_listing import (
    MergeRequestListing as _MergeRequestListing,
)


class GitLabMergeRequestClient(_MergeRequestListing):
    def create_merge_request(
        self,
        project: str | int,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        remove_source_branch: bool = False,
        squash: bool = False,
        draft: bool = False,
    ) -> MergeRequestResult:
        selector = self.project_selector(project)
        mr_title = merge_request_title(title, draft=draft)
        payload = MergeRequestCreate(
            source_branch=source_branch,
            target_branch=target_branch,
            title=mr_title,
            description=description,
            remove_source_branch=remove_source_branch,
            squash=squash,
        )
        data = self.request_model(
            "POST",
            f"/projects/{selector}/merge_requests",
            payload=payload,
            response_type=MergeRequest,
        ).data
        return MergeRequestResult(
            profile_id=self.profile.profile_id, project=str(project), merge_request=data
        )

    def update_merge_request(
        self,
        project: str | int,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        remove_source_branch: bool | None = None,
        squash: bool | None = None,
    ) -> MergeRequestResult:
        selector = self.project_selector(project)
        MergeRequestUpdate(
            title,
            description,
            state_event,
            target_branch,
            remove_source_branch,
            squash,
        ).require_changes()
        payload = MergeRequestUpdateBody(
            title=title,
            description=description,
            state_event=state_event,
            target_branch=target_branch,
            remove_source_branch=remove_source_branch,
            squash=squash,
        )
        data = self.request_model(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}",
            payload=payload,
            response_type=MergeRequest,
        ).data
        return MergeRequestResult(
            profile_id=self.profile.profile_id, project=str(project), merge_request=data
        )

    def list_merge_request_diffs(
        self,
        project: str | int,
        iid: int,
        page: int = 1,
        per_page: int = 100,
    ) -> MergeRequestDiffPage:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/merge_requests/{iid}/diffs",
            response_type=DiffRecords,
            query=PageQuery(page=page, per_page=per_page),
        )
        return MergeRequestDiffPage(
            profile_id=self.profile.profile_id,
            project=str(project),
            iid=iid,
            diffs=response.data.root,
            next_page=response.pagination.next_page,
        )

    def merge_merge_request(
        self,
        project: str | int,
        iid: int,
        sha: str = "",
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> MergeRequestResult:
        selector = self.project_selector(project)
        payload = MergeRequestAccept(
            merge_when_pipeline_succeeds=merge_when_pipeline_succeeds,
            sha=sha or None,
            squash=squash,
            should_remove_source_branch=should_remove_source_branch,
            merge_commit_message=merge_commit_message or None,
            squash_commit_message=squash_commit_message or None,
        )
        data = self.request_model(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}/merge",
            payload=payload,
            response_type=MergeRequest,
        ).data
        return MergeRequestResult(
            profile_id=self.profile.profile_id, project=str(project), merge_request=data
        )
