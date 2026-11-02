from __future__ import annotations

from dataclasses import dataclass, field

from pydantic import BaseModel

from service_runtime.http_transport import HttpTransportError as HttpTransportError
from service_runtime.http_transport import HttpTransportResponse
from source_control.providers.github.github_agent import _GITHUB_API as _GITHUB_API
from source_control.providers.github.github_agent import _GITHUB_API_VERSION as _GITHUB_API_VERSION
from source_control.providers.github.github_agent import GitHubAgentError as GitHubAgentError
from source_control.providers.github.github_agent import GitHubAppClient as _SharedGitHubAppClient
from svc_hand.domain.local_git import CheckoutReceipt

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
from .infrastructure.schemas.repository import RepositoryVisibility
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


@dataclass
class GitHubAppClient(_SharedGitHubAppClient):
    protected_branches: frozenset[str] = frozenset()

    _public_fallback_repositories: set[str] = field(default_factory=set, init=False, repr=False)

    def _observe_response(self, response: HttpTransportResponse) -> None:
        self._last_response_headers = {
            key.casefold(): value for key, value in response.headers.items()
        }

    def _outside_installation_response(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None,
        allowed_errors: set[int] | None,
        cause: GitHubAgentError,
    ) -> HttpTransportResponse:
        # A selected App can read public repositories outside its installation.
        # Verify visibility without credentials before falling back; never retry writes.
        visibility = self._request_transport(
            "GET", f"{_GITHUB_API}/repos/{repository}", auth_mode="public_anonymous"
        )
        if (
            visibility.status != 200
            or not RepositoryVisibility.model_validate_json(visibility.body).is_public
        ):
            raise GitHubAgentError("Public repository visibility required") from cause
        fallbacks = self._public_fallback_repositories
        fallbacks.add(repository.casefold())
        self._public_fallback_repositories = fallbacks
        if path.split("?", 1)[0] == f"/repos/{repository}":
            return visibility
        return self._request_transport(
            method,
            f"{_GITHUB_API}{path}",
            payload=payload,
            allowed_errors=allowed_errors,
            auth_mode="public_anonymous",
        )

    def status(self, repository: str) -> RepositoryStatus:
        repository = self._assert_allowed(repository)
        result = self._repository_metadata(repository)
        response: RepositoryStatus = RepositoryStatus(
            repository=str(result.repository),
            default_branch=str(result.default_branch),
            private=bool(result.private),
            auth_type=self.auth_type,
            status="ok",
        )
        if self.public_only:
            response.auth_type = "public"
            response.access_mode = "public_authenticated" if self.token else "public_anonymous"
            response.public_reader_account = self.public_reader_account
            response.rate_limits = self.rate_limit_status()
            return response
        if self.token:
            response.access_mode = "user_token"
            response.rate_limits = self.rate_limit_status()
            return response
        response.app_id = self.app_id
        if repository.casefold() in self._public_fallback_repositories:
            response.access_mode = "public_anonymous"
            response.read_only = True
            response.rate_limits = self.rate_limit_status()
            return response
        response.installation_id = self._installation_id(repository)
        response.access_mode = "installation"
        response.rate_limits = self.rate_limit_status()
        return response

    def checkout_repository(
        self,
        repository: str,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> GitHubCheckout | CheckoutReceipt:
        return self._checkout_repository(
            repository, destination, mode=mode, ref=ref, overwrite=overwrite
        )
