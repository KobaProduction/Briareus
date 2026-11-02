from __future__ import annotations

from source_control.providers.github.github_workflow import (
    GitHubDevClient as _SharedGitHubDevClient,
)

from .contents import GitHubContentsClient
from .issues import GitHubIssueClient
from .pulls import GitHubPullClient
from .refs import GitHubRefsClient
from .runs import GitHubRunClient


class GitHubDevClient(
    _SharedGitHubDevClient,
    GitHubContentsClient,
    GitHubRefsClient,
    GitHubPullClient,
    GitHubIssueClient,
    GitHubRunClient,
):
    pass
