from __future__ import annotations

from collections.abc import Callable

from mcp.types import ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar

from .activity_views import (
    JobTrace,
    PipelineJobs,
    PipelineList,
    PipelineResult,
)
from .pipelines import GitLabPipelineClient


def register_gitlab_pipeline_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabPipelineClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list pipelines", annotations=read_annotations)
    def list_pipelines(
        account_id: str,
        project: str,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> PipelineList:
        """List project pipelines."""
        return client_factory(account_id).list_pipelines(project, ref, status, page, per_page)

    @mcp.tool(title="GitLab pipeline jobs", annotations=read_annotations)
    def list_pipeline_jobs(
        account_id: str,
        project: str,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> PipelineJobs:
        """List jobs for one pipeline."""
        return client_factory(account_id).list_pipeline_jobs(project, pipeline_id, page, per_page)

    @mcp.tool(title="GitLab job trace", annotations=read_annotations)
    def job_trace(
        account_id: str,
        project: str,
        job_id: int,
        max_chars: int = 100_000,
    ) -> JobTrace:
        """Return the tail of one GitLab CI job trace."""
        return client_factory(account_id).job_trace(project, job_id, max_chars)

    @mcp.tool(title="GitLab retry pipeline", annotations=write_annotations)
    def retry_pipeline(
        account_id: str,
        project: str,
        pipeline_id: int,
    ) -> PipelineResult:
        """Retry failed/canceled jobs in a pipeline according to GitLab semantics."""
        return client_factory(account_id).retry_pipeline(project, pipeline_id)

    @mcp.tool(title="GitLab cancel pipeline", annotations=destructive_annotations)
    def cancel_pipeline(
        account_id: str,
        project: str,
        pipeline_id: int,
    ) -> PipelineResult:
        """Cancel a running GitLab pipeline."""
        return client_factory(account_id).cancel_pipeline(project, pipeline_id)
