"""GitHub observation contracts; provider permissions remain provider-owned data."""

from pydantic import BaseModel, ConfigDict

from .identity_views import GitHubActor
from .infrastructure.schemas.rate_limits import ProviderRateLimits
from .infrastructure.schemas.repository import RepositoryPushPermissions


class RateLimitObservation(BaseModel):
    model_config = ConfigDict(frozen=True)
    resource: str
    auth_mode: str
    http_status: int
    limit: int | None
    remaining: int | None
    used: int | None
    reset_epoch: int | None
    reset_at: str
    reset_in_seconds: int | None
    retry_after_seconds: int | None
    observed_at: str


class RateLimitStatus(BaseModel):
    auth_type: str
    public_only: bool
    public_reader_account: str
    entries: list[RateLimitObservation]


class RefreshedRateLimits(BaseModel):
    account_id: str
    auth_type: str
    access_mode: str
    repository: str
    public_reader_account: str
    provider: ProviderRateLimits
    observed: list[RateLimitObservation]


class RepositoryStatus(BaseModel):
    repository: str
    default_branch: str
    private: bool
    auth_type: str
    status: str
    access_mode: str = ""
    public_reader_account: str | None = None
    app_id: str | None = None
    installation_id: int | None = None
    read_only: bool | None = None
    rate_limits: RateLimitStatus | None = None
    app_identity: GitHubActor | None = None


class AccessibleRepository(BaseModel):
    full_name: str
    private: bool
    default_branch: str
    archived: bool
    fork: bool
    permissions: RepositoryPushPermissions
    installation_id: int | None = None


class RepositoryList(BaseModel):
    auth_type: str
    count: int
    repositories: list[AccessibleRepository]
    app_id: str | None = None
    note: str | None = None
    app_identity: GitHubActor | None = None
