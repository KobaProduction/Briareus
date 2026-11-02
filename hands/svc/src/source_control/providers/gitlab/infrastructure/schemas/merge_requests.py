"""Merge request provider contracts built from shared work-item and repository schemas."""

from pydantic import BaseModel, RootModel

from .activity import IssueMilestone
from .identity import GitLabUser
from .pagination import PageQuery
from .pipelines import PipelineSummary
from .work_items import GitLabWorkItem, WorkItemUpdate


class MergeRequest(GitLabWorkItem):
    target_branch: str
    source_branch: str
    source_project_id: int
    target_project_id: int
    sha: str
    merge_commit_sha: str | None = None
    squash_commit_sha: str | None = None
    draft: bool = False
    work_in_progress: bool = False
    milestone: IssueMilestone | None = None
    merged_by: GitLabUser | None = None
    merge_user: GitLabUser | None = None
    merged_at: str | None = None
    closed_by: GitLabUser | None = None
    closed_at: str | None = None
    merge_status: str | None = None
    detailed_merge_status: str | None = None
    merge_error: str | None = None
    merge_when_pipeline_succeeds: bool = False
    should_remove_source_branch: bool | None = None
    force_remove_source_branch: bool = False
    allow_collaboration: bool = False
    allow_maintainer_to_push: bool = False
    squash: bool = False
    squash_on_merge: bool = False
    user_notes_count: int = 0
    upvotes: int = 0
    downvotes: int = 0
    discussion_locked: bool | None = None
    has_conflicts: bool = False
    blocking_discussions_resolved: bool | None = None
    rebase_in_progress: bool | None = None
    diverged_commits_count: int | None = None
    pipeline: PipelineSummary | None = None
    head_pipeline: PipelineSummary | None = None


class MergeRequestRecords(RootModel[list[MergeRequest]]):
    pass


class MergeRequestQuery(PageQuery):
    state: str | None
    source_branch: str | None
    target_branch: str | None


class MergeRequestDetailsQuery(BaseModel):
    include_diverged_commits_count: bool = True
    include_rebase_in_progress: bool = True


class MergeRequestCreate(BaseModel):
    source_branch: str
    target_branch: str
    title: str
    description: str
    remove_source_branch: bool
    squash: bool


class MergeRequestUpdate(WorkItemUpdate):
    target_branch: str | None
    remove_source_branch: bool | None
    squash: bool | None
