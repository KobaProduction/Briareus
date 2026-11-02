"""Reusable resource command and redacted receipt contracts for the legacy BFF."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from projects._resource_domain import EffectiveResource, OwnerScope, ResourceKind, ResourceOwner
from runtime_peer.provider_settings import ProviderSettingsInput


class ResourceApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceView(ResourceApiModel):
    resource_id: UUID
    kind: ResourceKind
    name: str
    version: int
    project_access_revision: str | None = None
    team_access_revision: str | None = None
    owner_scope: OwnerScope
    owner_id: UUID
    origin: OwnerScope
    inherited: bool
    is_secret: bool
    masked: bool
    provider: str | None = None
    auth_type: str | None = None
    display_name: str = ""
    provider_settings: ProviderSettingsInput | None = None
    credential_configured: bool = False
    connection_status: str | None = None
    updated_at: datetime | None = None
    value: str | None = None

    @classmethod
    def from_effective(
        cls,
        resource: EffectiveResource,
        *,
        project_access_revision: str | None = None,
        team_access_revision: str | None = None,
    ) -> ResourceView:
        return cls(
            resource_id=resource.resource_id,
            kind=resource.kind,
            name=resource.name,
            version=resource.version,
            project_access_revision=project_access_revision,
            team_access_revision=team_access_revision,
            owner_scope=resource.owner.scope,
            owner_id=resource.owner.owner_id,
            origin=resource.origin,
            inherited=resource.inherited,
            is_secret=resource.is_secret,
            masked=resource.is_secret,
            provider=resource.provider,
            auth_type=resource.auth_type,
            display_name=resource.display_name,
            provider_settings=(
                ProviderSettingsInput.from_record(resource.provider_settings)
                if resource.provider_settings is not None
                else None
            ),
            credential_configured=resource.credential_configured,
            connection_status=resource.connection_status,
            updated_at=resource.updated_at,
            value=None if resource.is_secret else resource.value,
        )


class ProviderCatalogEntry(ResourceApiModel):
    provider: str
    auth_types: list[str]
    connectivity_status: str = "unverified"


class ProviderCatalog(ResourceApiModel):
    providers: list[ProviderCatalogEntry]
    network_verification_available: bool = False


class ResourceOwnerInput(ResourceApiModel):
    owner_scope: OwnerScope
    owner_id: UUID

    def owner(self) -> ResourceOwner:
        return ResourceOwner(self.owner_scope, self.owner_id)


class CreateIntegration(ResourceOwnerInput):
    alias: str = Field(min_length=1, max_length=128)
    provider: str = Field(min_length=1, max_length=32)
    auth_type: str = Field(min_length=1, max_length=32)
    provider_settings: ProviderSettingsInput = Field(default_factory=ProviderSettingsInput)
    credential: SecretStr = Field(min_length=1)


class UpdateIntegration(ResourceApiModel):
    expected_version: int = Field(ge=1)
    alias: str | None = Field(default=None, min_length=1, max_length=128)
    provider_settings: ProviderSettingsInput | None = None


class RotateIntegration(ResourceApiModel):
    expected_version: int = Field(ge=1)
    credential: SecretStr = Field(min_length=1)


class CreateVariable(ResourceOwnerInput):
    name: str = Field(min_length=1, max_length=128)
    value: SecretStr
    is_secret: bool = True


class UpdateVariable(ResourceApiModel):
    expected_version: int = Field(ge=1)
    name: str = Field(min_length=1, max_length=128)


class RotateVariable(ResourceApiModel):
    expected_version: int = Field(ge=1)
    value: SecretStr
    is_secret: bool = True


class DeleteResource(ResourceApiModel):
    expected_version: int = Field(ge=1)


class RevokedResource(ResourceApiModel):
    resource_id: UUID
    revoked: bool
    new_version: int
