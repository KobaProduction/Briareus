from __future__ import annotations

from source_control.providers.github.github_identity import _GITHUB_API as _GITHUB_API
from source_control.providers.github.github_identity import (
    GitHubPrettyIdentityClient as _SharedGitHubPrettyIdentityClient,
)

from .account_views import GitHubAccountCapabilities as GitHubAccountCapabilities
from .account_views import ProviderIdentity as ProviderIdentity
from .domain.history import GitIdentity as GitIdentity
from .github_actions import GitHubActionsClient
from .github_agent import GitHubAgentError as GitHubAgentError
from .identity_views import GitHubActor as GitHubActor
from .infrastructure.schemas.identity import AppRecord as AppRecord
from .infrastructure.schemas.identity import UserRecord as UserRecord
from .infrastructure.schemas.permissions import AppPermissions as AppPermissions
from .infrastructure.schemas.repository import AnnotatedTagCreate as AnnotatedTagCreate
from .infrastructure.schemas.repository import CommitAuthors as CommitAuthors
from .infrastructure.schemas.repository import GitSignatureRequest as GitSignatureRequest
from .local_git_views import WorkspaceGitAuthorization as WorkspaceGitAuthorization
from .local_git_views import WorkspaceGitPush as WorkspaceGitPush
from .provider_views import RepositoryList as RepositoryList
from .provider_views import RepositoryStatus as RepositoryStatus


class GitHubPrettyIdentityClient(_SharedGitHubPrettyIdentityClient, GitHubActionsClient):
    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> WorkspaceGitAuthorization:
        return self._authorize_local_git(repository, destination, remote=remote)

    def push_local_git(
        self,
        repository: str,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> WorkspaceGitPush:
        return self._push_local_git(
            repository, destination, branch=branch, remote=remote, set_upstream=set_upstream
        )
