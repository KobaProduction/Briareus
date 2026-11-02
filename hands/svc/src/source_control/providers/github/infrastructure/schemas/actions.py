"""Actions and checks share a run state; provider records stay outside domain gates."""

from pydantic import BaseModel, StrictBool, StrictFloat, StrictInt, StrictStr

from .pagination import PageQuery
from .requests import GitHubRequestBody


class RunState(BaseModel):
    name: str | None = None
    status: str
    conclusion: str | None = None


class WorkflowJobRecord(RunState):
    id: int
    html_url: str | None = None


class WorkflowRunRecord(WorkflowJobRecord):
    head_branch: str | None = None
    head_sha: str
    event: str


class WorkflowRuns(BaseModel):
    workflow_runs: list[WorkflowRunRecord]


class WorkflowJobs(BaseModel):
    jobs: list[WorkflowJobRecord]


class ArtifactMetadata(BaseModel):
    id: int
    name: str
    size_in_bytes: int
    expired: bool


class ArtifactRecord(ArtifactMetadata):
    created_at: str | None = None
    expires_at: str | None = None


class WorkflowArtifacts(BaseModel):
    artifacts: list[ArtifactRecord]
    total_count: int | None = None


class WorkflowRunQuery(PageQuery):
    branch: str | None = None
    status: str | None = None


class ApplicationSummary(BaseModel):
    slug: str | None = None


class CheckRunRecord(RunState):
    app: ApplicationSummary | None = None
    details_url: str | None = None


class CheckRuns(BaseModel):
    check_runs: list[CheckRunRecord]


class WorkflowDispatchRequest(GitHubRequestBody):
    ref: str
    inputs: dict[str, StrictStr | StrictBool | StrictInt | StrictFloat] | None = None
