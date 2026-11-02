from __future__ import annotations

from source_control.providers.github.github_agent import _GITHUB_API as _GITHUB_API
from source_control.providers.github.github_agent import _GITHUB_API_VERSION as _GITHUB_API_VERSION
from source_control.providers.github.github_agent import GitHubAgentError as GitHubAgentError
from source_control.providers.github.github_agent import GitHubAppClient as _SharedGitHubAppClient

from .domain.credentials import InstallationCredential as InstallationCredential
from .domain.repository import RepositoryMetadata as RepositoryMetadata
from .infrastructure.cache import CachedRepositoryMetadata as CachedRepositoryMetadata
from .infrastructure.schemas.installation import InstallationReference as InstallationReference
from .infrastructure.schemas.installation import InstallationReferences as InstallationReferences
from .infrastructure.schemas.installation import InstallationTokenReply as InstallationTokenReply
from .infrastructure.schemas.rate_limits import ProviderRateLimits as ProviderRateLimits
from .infrastructure.schemas.repository import (
    InstallationRepositoryRecords as InstallationRepositoryRecords,
)
from .infrastructure.schemas.repository import RepositoryRecord as RepositoryRecord
from .infrastructure.schemas.repository import RepositoryRecords as RepositoryRecords
from .infrastructure.schemas.requests import GitHubRequestBody as GitHubRequestBody
from .local_git_views import GitHubCheckout as GitHubCheckout
from .provider_views import AccessibleRepository as AccessibleRepository
from .provider_views import RateLimitObservation as RateLimitObservation
from .provider_views import RateLimitStatus as RateLimitStatus
from .provider_views import RefreshedRateLimits as RefreshedRateLimits
from .provider_views import RepositoryList as RepositoryList
from .provider_views import RepositoryStatus as RepositoryStatus
from .transport_views import GitHubAcknowledgement as GitHubAcknowledgement
from .transport_views import GitHubModelResponse as GitHubModelResponse
from .transport_views import GitHubPagination as GitHubPagination


class GitHubAppClient(_SharedGitHubAppClient):
    def checkout_repository(
        self,
        repository: str,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> GitHubCheckout:
        return self._checkout_repository(
            repository, destination, mode=mode, ref=ref, overwrite=overwrite
        )
