from __future__ import annotations

from modules.github.application.merge import LocalCleanupFailed as LocalCleanupFailed
from modules.github.application.merge import LocalWorktreeCleanup as LocalWorktreeCleanup
from source_control.providers.gitlab.merge_receipts import MergeRequestDiffPage, MergeRequestResult
from source_control.providers.gitlab.merge_request_listing import (
    MergeRequestListing as _MergeRequestListing,
)

from .api import GitLabApiClient as GitLabApiClient
from .domain.mutations import MergeRequestUpdate as MergeRequestUpdate
from .domain.mutations import merge_request_title as merge_request_title
from .domain.mutations import require_note_body as require_note_body
from .errors import GitLabError as GitLabError
from .infrastructure.schemas.activity import GitLabNote as GitLabNote
from .infrastructure.schemas.activity import NoteCreate as NoteCreate
from .infrastructure.schemas.merge_requests import MergeRequest as MergeRequest
from .infrastructure.schemas.merge_requests import MergeRequestAccept as MergeRequestAccept
from .infrastructure.schemas.merge_requests import MergeRequestCreate as MergeRequestCreate
from .infrastructure.schemas.merge_requests import (
    MergeRequestDetailsQuery as MergeRequestDetailsQuery,
)
from .infrastructure.schemas.merge_requests import MergeRequestQuery as MergeRequestQuery
from .infrastructure.schemas.merge_requests import MergeRequestRecords as MergeRequestRecords
from .infrastructure.schemas.merge_requests import MergeRequestUpdate as MergeRequestUpdateBody
from .infrastructure.schemas.pagination import PageQuery as PageQuery
from .infrastructure.schemas.repository import DiffRecords as DiffRecords
from .infrastructure.schemas.repository import GitLabBranch as GitLabBranch
from .merge_views import MergeRequestMerged as MergeRequestMerged


class GitLabMergeRequestClient(_MergeRequestListing):
    def create_merge_request(
        self,
        project: str | int,
        source_branch: str,
        target_branch: str,
        title: str,
        delete_source_branch_after_merge: bool,
        description: str = "",
        squash: bool = False,
        draft: bool = False,
    ) -> MergeRequestResult:
        if type(delete_source_branch_after_merge) is not bool:
            raise GitLabError("Explicit keep/delete source branch choice required")
        selector = self.project_selector(project)
        mr_title = merge_request_title(title, draft=draft)
        payload = MergeRequestCreate(
            source_branch=source_branch,
            target_branch=target_branch,
            title=mr_title,
            description=description,
            remove_source_branch=delete_source_branch_after_merge,
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
        delete_source_branch_after_merge: bool | None = None,
        squash: bool | None = None,
    ) -> MergeRequestResult:
        selector = self.project_selector(project)
        payload = MergeRequestUpdateBody(
            title=title,
            description=description,
            state_event=state_event,
            target_branch=target_branch,
            remove_source_branch=delete_source_branch_after_merge,
            squash=squash,
        )
        MergeRequestUpdate(
            title, description, state_event, target_branch, delete_source_branch_after_merge, squash
        ).require_changes()
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
            query=PageQuery(page=page, per_page=per_page),
            response_type=DiffRecords,
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
        delete_source_branch_after_merge: bool,
        sha: str = "",
        squash: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> MergeRequestMerged:
        branch_deletion_choice: object = delete_source_branch_after_merge
        if type(branch_deletion_choice) is not bool or not sha:
            raise GitLabError("Explicit keep/delete choice and expected source sha required")
        selector = self.project_selector(project)
        current = self.request_model(
            "GET", f"/projects/{selector}/merge_requests/{iid}", response_type=MergeRequest
        ).data
        if current.sha != sha:
            raise GitLabError("Merge request head changed")
        if current.source_project_id != current.target_project_id:
            raise GitLabError("Cross-project merge cleanup is disabled")
        source_branch = current.source_branch
        if delete_source_branch_after_merge:
            from .policy import require_mutable_branch

            require_mutable_branch(source_branch, self.protected_branches)
            branch = self.request_model(
                "GET",
                f"/projects/{selector}/repository/branches/{self.project_selector(source_branch)}",
                response_type=GitLabBranch,
            ).data
            if branch.protected or branch.default or source_branch == current.target_branch:
                raise GitLabError("Cannot remove protected/default/target branch")
        elif current.force_remove_source_branch:
            raise GitLabError("Project forced deletion conflicts with explicit keep choice")
        payload = MergeRequestAccept(
            merge_when_pipeline_succeeds=merge_when_pipeline_succeeds,
            sha=sha,
            squash=squash,
            should_remove_source_branch=delete_source_branch_after_merge,
            merge_commit_message=merge_commit_message or None,
            squash_commit_message=squash_commit_message or None,
        )
        data = self.request_model(
            "PUT",
            f"/projects/{selector}/merge_requests/{iid}/merge",
            payload=payload,
            response_type=MergeRequest,
        ).data
        cleanup: LocalWorktreeCleanup | LocalCleanupFailed | None = None
        merged = data.state == "merged"
        if merged and delete_source_branch_after_merge:
            try:
                cleanup = self._cleanup_merged_worktrees(str(project), source_branch, sha)
            except Exception:
                cleanup = LocalCleanupFailed()
        return MergeRequestMerged(
            profile_id=self.profile.profile_id,
            project=str(project),
            merge_request=data,
            source_branch_action="delete" if delete_source_branch_after_merge else "keep",
            local_cleanup=cleanup,
        )

    def _cleanup_merged_worktrees(
        self, _repository: str, _branch: str, _expected_head: str
    ) -> LocalWorktreeCleanup | None:
        """The node adapter supplies local checkout cleanup when available."""
        return None
