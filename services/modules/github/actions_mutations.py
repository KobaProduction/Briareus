from __future__ import annotations

from source_control.providers.github.actions_mutations import (
    GitHubActionsMutationClient as _SharedGitHubActionsMutationClient,
)

from .base import GitHubRepositoryClientBase
from .execution_views import WorkflowDispatched as WorkflowDispatched
from .execution_views import WorkflowEnabled as WorkflowEnabled
from .execution_views import WorkflowJobMutation as WorkflowJobMutation
from .execution_views import WorkflowRunMutation as WorkflowRunMutation
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.actions import WorkflowDispatchRequest as WorkflowDispatchRequest


class GitHubActionsMutationClient(_SharedGitHubActionsMutationClient, GitHubRepositoryClientBase):
    pass
