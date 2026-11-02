from __future__ import annotations

from source_control.providers.github.github_actions import (
    GitHubActionsClient as _SharedGitHubActionsClient,
)

from .actions_diagnostics import GitHubActionsDiagnosticsClient
from .actions_mutations import GitHubActionsMutationClient
from .contents import GitHubContentsClient
from .github_collab import GitHubCollabClient
from .issues import GitHubIssueClient
from .refs import GitHubRefsClient
from .runs import GitHubRunClient


class GitHubActionsClient(
    _SharedGitHubActionsClient,
    GitHubCollabClient,
    GitHubContentsClient,
    GitHubRefsClient,
    GitHubIssueClient,
    GitHubRunClient,
    GitHubActionsDiagnosticsClient,
    GitHubActionsMutationClient,
):
    pass
