"""Named owner command receipts before durable ledger serialization."""

from __future__ import annotations

from pydantic import BaseModel


class CatalogMetadataRecord(BaseModel):
    resource_id: str
    kind: str
    owner_scope: str
    owner_id: str
    name_key: str
    version: int


class CatalogChangeIntegration(BaseModel):
    resource_id: str
    version: int
    owner_scope: str
    revoked: bool


class CatalogChangeVariable(BaseModel):
    resource_id: str
    version: int
    owner_scope: str
    revoked: bool
    is_secret: bool


class CatalogCreateIntegration(BaseModel):
    resource_id: str
    owner_scope: str
    alias_key: str
    version: int
    credential_configured: bool


class CatalogCreateVariable(BaseModel):
    resource_id: str
    owner_scope: str
    name_key: str
    version: int
    is_secret: bool


class CatalogListMetadataCommitted(BaseModel):
    status: str
    kind: str
    scope: str
    alias_key: str | None
    limit: int
    project_id: str
    records: list[CatalogMetadataRecord]
    count: int
    source_secret_included: bool


class CatalogReserveIntegration(BaseModel):
    lease_id: str
    owner_scope: str
    owner_id: str
    resource_version: int
    expires_at: str


class CatalogReserveVariable(BaseModel):
    lease_id: str
    owner_scope: str
    owner_id: str
    resource_version: int
    expires_at: str
    credential_configured: bool


class CatalogResolveMetadataCommitted(BaseModel):
    status: str
    resource_id: str
    owner_scope: str
    owner_id: str
    name_key: str
    kind: str
    version: int
    source_secret_included: bool


class CatalogRevokeUnusedLease(BaseModel):
    status: str
    lease_id: str
    resource_id: str
    secret_returned: bool
