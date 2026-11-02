from __future__ import annotations

import urllib.parse

from .base import GitHubRepositoryClientBase
from .execution_views import (
    WorkflowDispatched,
    WorkflowEnabled,
    WorkflowJobMutation,
    WorkflowRunMutation,
)
from .github_agent import GitHubAgentError
from .infrastructure.schemas.actions import WorkflowDispatchRequest


class GitHubActionsMutationClient(GitHubRepositoryClientBase):
    def enable_workflow(
        self,
        repository: str,
        workflow_id: str,
    ) -> WorkflowEnabled:
        """Enable one GitHub Actions workflow in an installed repository."""
        repository = self._assert_allowed(repository)
        workflow = workflow_id.strip()
        if not workflow:
            raise GitHubAgentError("workflow_id must not be empty")

        workflow_q = urllib.parse.quote(workflow, safe="")
        receipt = self._repo_ack(
            repository,
            "PUT",
            f"/repos/{repository}/actions/workflows/{workflow_q}/enable",
        )
        return WorkflowEnabled(
            repository=repository,
            workflow_id=workflow,
            status=receipt.status,
            enabled=receipt.status in {200, 204},
        )

    def dispatch_workflow(
        self,
        repository: str,
        workflow_id: str,
        ref: str,
        inputs: dict[str, str | bool | int | float] | None = None,
    ) -> WorkflowDispatched:
        repository = self._assert_allowed(repository)
        workflow = workflow_id.strip()
        target_ref = ref.strip()
        if not workflow:
            raise GitHubAgentError("workflow_id must not be empty")
        if not target_ref:
            raise GitHubAgentError("ref must not be empty")

        workflow_q = urllib.parse.quote(workflow, safe="")
        payload = WorkflowDispatchRequest(ref=target_ref, inputs=inputs or None)

        receipt = self._repo_ack(
            repository,
            "POST",
            f"/repos/{repository}/actions/workflows/{workflow_q}/dispatches",
            payload=payload,
        )
        return WorkflowDispatched(
            repository=repository,
            workflow_id=workflow,
            ref=target_ref,
            inputs=dict(inputs or {}),
            status=receipt.status,
            dispatched=receipt.status in {201, 204},
        )

    def rerun_workflow_job(self, repository: str, job_id: int) -> WorkflowJobMutation:
        repository = self._assert_allowed(repository)
        receipt = self._repo_ack(
            repository,
            "POST",
            f"/repos/{repository}/actions/jobs/{job_id}/rerun",
        )
        return WorkflowJobMutation(repository=repository, job_id=job_id, status=receipt.status)

    def rerun_failed_workflow_jobs(
        self,
        repository: str,
        run_id: int,
    ) -> WorkflowRunMutation:
        repository = self._assert_allowed(repository)
        receipt = self._repo_ack(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/rerun-failed-jobs",
        )
        return WorkflowRunMutation(repository=repository, run_id=run_id, status=receipt.status)

    def rerun_workflow_run(self, repository: str, run_id: int) -> WorkflowRunMutation:
        repository = self._assert_allowed(repository)
        receipt = self._repo_ack(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/rerun",
        )
        return WorkflowRunMutation(repository=repository, run_id=run_id, status=receipt.status)

    def cancel_workflow_run(self, repository: str, run_id: int) -> WorkflowRunMutation:
        repository = self._assert_allowed(repository)
        receipt = self._repo_ack(
            repository,
            "POST",
            f"/repos/{repository}/actions/runs/{run_id}/cancel",
        )
        return WorkflowRunMutation(repository=repository, run_id=run_id, status=receipt.status)
