from __future__ import annotations

from source_control.providers.github.base import (
    GitHubRepositoryClientBase as _SharedGitHubRepositoryClientBase,
)

from .github_agent import GitHubAppClient
from .policy import require_mutable_branch as require_mutable_branch


class GitHubRepositoryClientBase(_SharedGitHubRepositoryClientBase, GitHubAppClient):
    pass
