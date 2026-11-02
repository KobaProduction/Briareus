"""Account catalog and provider capability observations, never authorization grants."""

from pydantic import BaseModel, Field

from source_control.account_views import SourceAccountView

from .identity_views import RepositoryCapabilities
from .infrastructure.schemas.permissions import AppPermissions


class GitHubAccountView(SourceAccountView):
    transport_auth: str | None = None
    reader_selector: str | None = None
    anonymous_fallback: bool | None = None


class GitHubAccountList(BaseModel):
    accounts: list[GitHubAccountView]
    count: int


class ProviderIdentity(BaseModel):
    login: str | None = None
    type: str | None = None
    name: str | None = None
    app_id: str | None = None
    slug: str | None = None


class GitHubAccountCapabilities(BaseModel):
    account_id: str
    auth_type: str
    identity: ProviderIdentity
    provider_permissions: AppPermissions
    provider_permissions_known: bool
    note: str
    transport_auth: str | None = None
    reader_account: str | None = None
    potential_capabilities: list[str] = Field(default_factory=list)
    permission_scope: str | None = None
    repository: RepositoryCapabilities | None = None
