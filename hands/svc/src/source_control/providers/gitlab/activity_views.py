"""Named gitlab results; serialization stays at the MCP boundary."""

from .infrastructure.schemas.activity import GitLabIssue, GitLabNote, PipelineJob
from .infrastructure.schemas.pipelines import PipelineDetails, PipelineSummary
from .repository_views import RepositoryResult


class IssueList(RepositoryResult):
    issues: list[GitLabIssue]
    next_page: str


class IssueNote(RepositoryResult):
    note: GitLabNote


class IssueResponse(RepositoryResult):
    issue: GitLabIssue


class JobTrace(RepositoryResult):
    job_id: int
    truncated: bool
    trace_tail: str


class PipelineJobs(RepositoryResult):
    pipeline_id: int
    jobs: list[PipelineJob]
    next_page: str


class PipelineList(RepositoryResult):
    pipelines: list[PipelineSummary]
    next_page: str


class PipelineResult(RepositoryResult):
    pipeline: PipelineDetails
