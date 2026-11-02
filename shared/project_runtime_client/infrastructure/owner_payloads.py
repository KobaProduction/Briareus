"""Field-exact accepted owner business preimages, separate from effect metadata."""

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class OwnerPeerPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    service_id: UUID
    instance_uuid: UUID


class FilesReservePayload(OwnerPeerPayload):
    path_digest: str
    content_sha256: str
    planned_bytes: int
    expected_file_version: int
    ttl_seconds: Literal[600] = 600


class FilesDispatchPayload(OwnerPeerPayload):
    reservation_id: UUID
    reservation_operation_uuid: UUID
    expected_reservation_version: int


class FilesTransitionPayload(OwnerPeerPayload):
    reservation_id: UUID
    original_operation_uuid: UUID
    expected_version: int


class RuntimeOpenPayload(OwnerPeerPayload):
    runtime_session_uuid: UUID
    kind: str
    idle_ttl_seconds: int
    hard_ttl_seconds: int


class RuntimeRenewPayload(OwnerPeerPayload):
    runtime_session_uuid: UUID
    expected_version: int
    expected_lease_nonce: UUID


class RuntimeRevokePayload(OwnerPeerPayload):
    runtime_session_uuid: UUID
    expected_version: int


class NativeDispatchPayload(OwnerPeerPayload):
    import_uuid: UUID
    original_operation_uuid: UUID
    expected_import_version: int


class NativeTransitionPayload(OwnerPeerPayload):
    import_uuid: UUID
    original_operation_uuid: UUID
    expected_version: int


class CatalogListPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="forbid")
    kind: str
    scope: str
    alias_key: None
    limit: int


type OwnerBusinessPayload = (
    FilesReservePayload
    | FilesDispatchPayload
    | FilesTransitionPayload
    | RuntimeOpenPayload
    | RuntimeRenewPayload
    | RuntimeRevokePayload
    | NativeDispatchPayload
    | NativeTransitionPayload
    | CatalogListPayload
)
