from __future__ import annotations

from collections.abc import Callable

from mcp.types import ToolAnnotations

from .contracts import ToolRegistrar
from .execution_views import (
    WorkflowJobList,
    WorkflowRunList,
)
from .github_actions import GitHubActionsClient


def register_github_run_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub agent workflow runs", annotations=read_annotations)
    def github_agent_workflow_runs(
        account_id: str,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> WorkflowRunList:
        """List GitHub Actions workflow runs."""
        return client_factory(account_id).list_workflow_runs(
            repository, branch, status, per_page, page
        )

    @mcp.tool(title="GitHub agent workflow jobs", annotations=read_annotations)
    def github_agent_workflow_jobs(
        account_id: str, repository: str, run_id: int
    ) -> WorkflowJobList:
        """List jobs for one GitHub Actions workflow run."""
        return client_factory(account_id).list_workflow_jobs(repository, run_id)
