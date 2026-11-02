"""Exact signed Catalog wire parameters; no coercion, secrets or added fields."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import TypeAdapter

from runtime_peer.provider_settings import ProviderSettingsInput


@dataclass(frozen=True, slots=True)
class ReserveIntegrationPayload:
    integration_id: str
    expected_resource_version: int
    owner_scope: str
    owner_id: str
    service_id: str
    service_instance_uuid: str
    service_audience: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class RedeemCatalogLeasePayload:
    lease_id: str
    service_id: str
    instance_uuid: str
    audience: str


@dataclass(frozen=True, slots=True)
class ListCatalogMetadataPayload:
    kind: str
    scope: str
    alias_key: str | None
    limit: int


@dataclass(frozen=True, slots=True)
class CreateCatalogVariablePayload:
    owner_scope: str
    owner_id: str
    name_key: str
    is_secret: bool
    value_hmac_sha256: str


@dataclass(frozen=True, slots=True)
class ChangeCatalogIntegrationPayload:
    integration_id: str
    owner_scope: str
    owner_id: str
    expected_version: int
    action: str
    new_credential_hmac_sha256: str | None


@dataclass(frozen=True, slots=True)
class ChangeCatalogVariablePayload:
    variable_id: str
    owner_scope: str
    owner_id: str
    expected_version: int
    action: str
    new_value_hmac_sha256: str | None


@dataclass(frozen=True, slots=True)
class ReserveVariablePayload:
    variable_id: str
    expected_resource_version: int
    owner_scope: str
    owner_id: str
    service_id: str
    service_instance_uuid: str
    service_audience: str
    expires_in_seconds: int


@dataclass(frozen=True, slots=True)
class ResolveCatalogMetadataPayload:
    kind: str
    resource_id: str
    owner_scope: str
    owner_id: str
    expected_resource_version: int


@dataclass(frozen=True, slots=True)
class CreateCatalogIntegrationPayload:
    owner_scope: str
    owner_id: str
    alias: str
    provider: str
    auth_type: str
    provider_settings: ProviderSettingsInput
    credential_hmac_sha256: str


@dataclass(frozen=True, slots=True)
class RevokeCatalogLeasePayload:
    lease_id: str
    service_id: str
    instance_uuid: str


CREATE_INTEGRATION_PAYLOAD = TypeAdapter(CreateCatalogIntegrationPayload)
