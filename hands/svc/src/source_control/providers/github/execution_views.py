"""Typed GitHub Actions and review results, serialized by the MCP adapter."""

from pydantic import BaseModel

from .comment_views import ConversationComment, InlineReviewComment
from .infrastructure.schemas.actions import ArtifactMetadata
from .ref_views import RepositoryResult


class ConversationComments(RepositoryResult):
    number: int
    comments: list[ConversationComment]
    page: int
    per_page: int
    returned_count: int
    has_next_page: bool
    next_page: int | None


class ReviewBranchUpdate(RepositoryResult):
    number: int
    head: str
    head_sha: str
    base: str
    mergeable: str
    method: str


class ReviewComments(RepositoryResult):
    number: int
    comments: list[InlineReviewComment]


class ReviewCreation(RepositoryResult):
    number: int
    review_id: int
    state: str
    commit_id: str


class WorkflowDispatched(RepositoryResult):
    workflow_id: str
    ref: str
    inputs: dict[str, str | bool | int | float]
    status: int
    dispatched: bool


class WorkflowEnabled(RepositoryResult):
    workflow_id: str
    status: int
    enabled: bool


class WorkflowFileDownload(RepositoryResult):
    workflow_file_id: int
    size: int
    sha256: str
    content_base64: str


class WorkflowArtifact(ArtifactMetadata):
    created_at: str
    expires_at: str


class WorkflowJob(BaseModel):
    id: int
    name: str
    status: str
    conclusion: str | None
    html_url: str


class WorkflowRun(WorkflowJob):
    head_branch: str
    head_sha: str
    event: str


class WorkflowFileList(RepositoryResult):
    run_id: int
    total_count: int
    files: list[WorkflowArtifact]
    page: int


class WorkflowJobList(RepositoryResult):
    run_id: int
    jobs: list[WorkflowJob]


class WorkflowJobLog(RepositoryResult):
    job_id: int
    log: str
    tail_chars: int
    truncated: bool
    downloaded_bytes: int


class WorkflowJobMutation(RepositoryResult):
    job_id: int
    status: int


class WorkflowRunList(RepositoryResult):
    workflow_runs: list[WorkflowRun]
    page: int


class WorkflowRunMutation(RepositoryResult):
    run_id: int
    status: int
