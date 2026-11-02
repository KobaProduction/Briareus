from __future__ import annotations

from .base import GitHubRepositoryClientBase
from .execution_views import (
    WorkflowJob,
    WorkflowJobList,
    WorkflowRun,
    WorkflowRunList,
)
from .infrastructure.schemas.actions import WorkflowJobs, WorkflowRunQuery, WorkflowRuns


class GitHubRunClient(GitHubRepositoryClientBase):
    def list_workflow_runs(
        self,
        repository: str,
        branch: str | None = None,
        status: str | None = None,
        per_page: int = 30,
        page: int = 1,
    ) -> WorkflowRunList:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs",
            response_type=WorkflowRuns,
            query=WorkflowRunQuery(
                per_page=max(1, min(per_page, 100)),
                page=max(1, page),
                branch=branch or None,
                status=status or None,
            ),
        ).data
        runs = [
            WorkflowRun(
                id=item.id,
                name=item.name or "",
                head_branch=item.head_branch or "",
                head_sha=item.head_sha,
                status=item.status,
                conclusion=item.conclusion,
                event=item.event,
                html_url=item.html_url or "",
            )
            for item in result.workflow_runs
        ]
        return WorkflowRunList(
            repository=repository,
            workflow_runs=runs,
            page=page,
        )

    def list_workflow_jobs(self, repository: str, run_id: int) -> WorkflowJobList:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/actions/runs/{run_id}/jobs?per_page=100",
            response_type=WorkflowJobs,
        ).data
        jobs = [
            WorkflowJob(
                id=item.id,
                name=item.name or "",
                status=item.status,
                conclusion=item.conclusion,
                html_url=item.html_url or "",
            )
            for item in result.jobs
        ]
        return WorkflowJobList(
            repository=repository,
            run_id=run_id,
            jobs=jobs,
        )
