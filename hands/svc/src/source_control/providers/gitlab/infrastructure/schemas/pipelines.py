"""Pipeline metadata reused by job, repository and workflow schemas."""

from pydantic import BaseModel

from .identity import GitLabUser


class PipelineSummary(BaseModel):
    id: int
    iid: int | None = None
    project_id: int | None = None
    sha: str
    ref: str
    status: str
    source: str | None = None
    name: str | None = None
    web_url: str | None = None
    created_at: str | None = None
    updated_at: str | None = None


class PipelineDetails(PipelineSummary):
    before_sha: str | None = None
    tag: bool = False
    yaml_errors: str | None = None
    user: GitLabUser | None = None
    started_at: str | None = None
    finished_at: str | None = None
    committed_at: str | None = None
    duration: float | None = None
    queued_duration: float | None = None
    coverage: str | None = None
