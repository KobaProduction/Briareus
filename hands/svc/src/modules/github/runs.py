from __future__ import annotations

from source_control.providers.github.runs import GitHubRunClient as _SharedGitHubRunClient

from .base import GitHubRepositoryClientBase
from .execution_views import WorkflowJob as WorkflowJob
from .execution_views import WorkflowJobList as WorkflowJobList
from .execution_views import WorkflowRun as WorkflowRun
from .execution_views import WorkflowRunList as WorkflowRunList
from .infrastructure.schemas.actions import WorkflowJobs as WorkflowJobs
from .infrastructure.schemas.actions import WorkflowRunQuery as WorkflowRunQuery
from .infrastructure.schemas.actions import WorkflowRuns as WorkflowRuns


class GitHubRunClient(_SharedGitHubRunClient, GitHubRepositoryClientBase):
    pass
