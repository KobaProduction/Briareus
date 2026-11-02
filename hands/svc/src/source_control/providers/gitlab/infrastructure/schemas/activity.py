"""GitLab issue and pipeline schemas validated at the provider boundary."""

from pydantic import BaseModel, Field, RootModel

from .identity import GitLabUser
from .pagination import PageQuery
from .pipelines import PipelineSummary
from .repository import GitLabCommit
from .work_items import GitLabWorkItem, WorkItemUpdate


class IssueMilestone(BaseModel):
    id: int
    iid: int
    title: str
    description: str | None = None
    state: str
    due_date: str | None = None
    start_date: str | None = None
    web_url: str | None = None


class IssueTimeStats(BaseModel):
    time_estimate: int = 0
    total_time_spent: int = 0
    human_time_estimate: str | None = None
    human_total_time_spent: str | None = None


class IssueLinks(BaseModel):
    self: str | None = None
    notes: str | None = None
    award_emoji: str | None = None
    project: str | None = None
    closed_as_duplicate_of: str | None = None


class TaskCompletion(BaseModel):
    count: int
    completed_count: int


class GitLabIssue(GitLabWorkItem):
    closed_at: str | None = None
    closed_by: GitLabUser | None = None
    milestone: IssueMilestone | None = None
    type: str | None = None
    issue_type: str | None = None
    user_notes_count: int = 0
    merge_requests_count: int = 0
    upvotes: int = 0
    downvotes: int = 0
    due_date: str | None = None
    confidential: bool = False
    discussion_locked: bool | None = None
    time_stats: IssueTimeStats | None = None
    task_completion_status: TaskCompletion | None = None
    weight: int | None = None
    health_status: str | None = None
    blocking_issues_count: int = 0
    has_tasks: bool = False
    task_status: str | None = None
    links: IssueLinks | None = Field(default=None, alias="_links")


class GitLabNote(BaseModel):
    id: int
    type: str | None = None
    body: str
    author: GitLabUser
    created_at: str
    updated_at: str
    system: bool = False
    noteable_id: int
    noteable_type: str
    noteable_iid: int | None = None
    resolvable: bool = False
    confidential: bool = False
    internal: bool = False
    imported: bool = False
    imported_from: str | None = None


class JobArtifact(BaseModel):
    file_type: str
    size: int
    filename: str
    file_format: str | None = None


class JobArtifactFile(BaseModel):
    filename: str
    size: int


class JobRunner(BaseModel):
    id: int
    description: str | None = None
    ip_address: str | None = None
    active: bool | None = None
    paused: bool | None = None
    is_shared: bool | None = None
    runner_type: str | None = None
    name: str | None = None
    online: bool | None = None
    status: str | None = None


class PipelineJob(BaseModel):
    id: int
    name: str
    stage: str
    status: str
    ref: str
    tag: bool = False
    allow_failure: bool = False
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    erased_at: str | None = None
    duration: float | None = None
    queued_duration: float | None = None
    user: GitLabUser | None = None
    commit: GitLabCommit | None = None
    pipeline: PipelineSummary | None = None
    web_url: str
    artifacts_file: JobArtifactFile | None = None
    artifacts: list[JobArtifact] = Field(default_factory=list)
    runner: JobRunner | None = None
    artifacts_expire_at: str | None = None
    archived: bool = False
    failure_reason: str | None = None
    coverage: float | None = None
    tag_list: list[str] = Field(default_factory=list)


class IssueRecords(RootModel[list[GitLabIssue]]):
    pass


class PipelineRecords(RootModel[list[PipelineSummary]]):
    pass


class PipelineJobRecords(RootModel[list[PipelineJob]]):
    pass


class IssueQuery(PageQuery):
    state: str | None
    search: str | None


class IssueCreate(BaseModel):
    title: str
    description: str
    labels: str | None = None


class IssueUpdate(WorkItemUpdate):
    labels: str | None


class NoteCreate(BaseModel):
    body: str


class PipelineQuery(PageQuery):
    ref: str | None
    status: str | None
    order_by: str = "id"
    sort: str = "desc"


class PipelineJobQuery(PageQuery):
    pass
