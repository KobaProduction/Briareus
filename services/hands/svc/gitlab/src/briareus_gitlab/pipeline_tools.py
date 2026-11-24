from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from briareus_git.ci import CINames, register_ci_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gitlab_client import GitLabClient


def register_gitlab_pipeline_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    register_ci_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
        destructive_annotations,
        "GitLab",
        CINames("job_trace", "retry_pipeline", "cancel_pipeline"),
    )

    @mcp.tool(title="GitLab list pipelines", annotations=read_annotations)
    def list_pipelines(
        account_id: str,
        project: str,
        ref: str = "",
        status: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List project pipelines."""
        return client_factory(account_id).list_pipelines(project, ref, status, page, per_page)

    @mcp.tool(title="GitLab pipeline jobs", annotations=read_annotations)
    def list_pipeline_jobs(
        account_id: str,
        project: str,
        pipeline_id: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List jobs for one pipeline."""
        return client_factory(account_id).list_pipeline_jobs(project, pipeline_id, page, per_page)

    _register_pipeline_operations(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations
    )


def _register_pipeline_operations(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab create pipeline", annotations=write_annotations)
    def create_pipeline(
        account_id: str,
        project: str,
        ref: str,
        variables: dict[str, str] | None = None,
        inputs: JsonObject | None = None,
    ) -> JsonObject:
        """Start a pipeline on an explicit branch/tag with optional variables or inputs."""
        return client_factory(account_id).create_pipeline(project, ref, variables, inputs)

    @mcp.tool(title="GitLab get pipeline", annotations=read_annotations)
    def get_pipeline(account_id: str, project: str, pipeline_id: int) -> JsonObject:
        """Read one pipeline and its current status."""
        return client_factory(account_id).get_pipeline(project, pipeline_id)

    @mcp.tool(title="GitLab get job", annotations=read_annotations)
    def get_job(account_id: str, project: str, job_id: int) -> JsonObject:
        """Read one CI/CD job, including available artifact metadata."""
        return client_factory(account_id).get_job(project, job_id)

    @mcp.tool(title="GitLab control job", annotations=destructive_annotations)
    def control_job(
        account_id: str, project: str, job_id: int, action: Literal["retry", "cancel", "play"]
    ) -> JsonObject:
        """Retry, cancel, or start a manual CI/CD job."""
        return client_factory(account_id).control_job(project, job_id, action)

    @mcp.tool(title="GitLab download job artifacts", annotations=read_annotations)
    def download_job_artifacts(
        account_id: str, project: str, job_id: int, path: str = "", max_bytes: int = 8 * 1024 * 1024
    ) -> JsonObject:
        """Download a small artifact archive or one relative file as base64 with SHA-256."""
        return client_factory(account_id).download_job_artifacts(project, job_id, path, max_bytes)

    @mcp.tool(title="GitLab list commit statuses", annotations=read_annotations)
    def list_commit_statuses(
        account_id: str, project: str, sha: str, page: int = 1, per_page: int = 100
    ) -> JsonObject:
        """Read commit statuses; paginate and consult MR merge status for actual requirements."""
        return client_factory(account_id).list_commit_statuses(project, sha, page, per_page)
