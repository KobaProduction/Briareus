from __future__ import annotations

from .actions_diagnostics import GitHubActionsDiagnosticsClient
from .actions_mutations import GitHubActionsMutationClient
from .contents import GitHubContentsClient
from .github_collab import GitHubCollabClient
from .github_history import GitHubHistoryMixin
from .issues import GitHubIssueClient
from .refs import GitHubRefsClient
from .runs import GitHubRunClient


class GitHubActionsClient(
    GitHubHistoryMixin,
    GitHubCollabClient,
    GitHubContentsClient,
    GitHubRefsClient,
    GitHubIssueClient,
    GitHubRunClient,
    GitHubActionsDiagnosticsClient,
    GitHubActionsMutationClient,
):
    """Full GitHub client composed from repository, review, history, and Actions capabilities."""
