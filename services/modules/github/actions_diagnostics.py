from __future__ import annotations

from source_control.providers.github.actions_diagnostics import _GITHUB_API as _GITHUB_API
from source_control.providers.github.actions_diagnostics import _MAX_LOG_BYTES as _MAX_LOG_BYTES
from source_control.providers.github.actions_diagnostics import (
    _MAX_WORKFLOW_FILE_BYTES as _MAX_WORKFLOW_FILE_BYTES,
)
from source_control.providers.github.actions_diagnostics import (
    GitHubActionsDiagnosticsClient as _SharedGitHubActionsDiagnosticsClient,
)
from source_control.providers.github.actions_diagnostics import _NoRedirect as _NoRedirect

from .base import GitHubRepositoryClientBase
from .execution_views import WorkflowArtifact as WorkflowArtifact
from .execution_views import WorkflowFileDownload as WorkflowFileDownload
from .execution_views import WorkflowFileList as WorkflowFileList
from .execution_views import WorkflowJobLog as WorkflowJobLog
from .github_agent import GitHubAgentError as GitHubAgentError
from .infrastructure.schemas.actions import WorkflowArtifacts as WorkflowArtifacts
from .infrastructure.schemas.pagination import PageQuery as PageQuery


class GitHubActionsDiagnosticsClient(
    _SharedGitHubActionsDiagnosticsClient, GitHubRepositoryClientBase
):
    pass
