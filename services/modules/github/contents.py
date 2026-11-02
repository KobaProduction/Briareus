from __future__ import annotations

from source_control.providers.github.contents import (
    GitHubContentsClient as _SharedGitHubContentsClient,
)

from .content_api import GitHubContentApiClient
from .git_mutations import GitHubGitMutationClient


class GitHubContentsClient(
    _SharedGitHubContentsClient, GitHubContentApiClient, GitHubGitMutationClient
):
    pass
