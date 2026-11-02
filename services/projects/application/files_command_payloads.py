"""Exact finite Files signed input shapes; observation is the approved wire subset only."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class FilesReserveWritePayload:
    service_id: str
    instance_uuid: str
    path_digest: str
    content_sha256: str
    planned_bytes: int
    expected_file_version: int
    ttl_seconds: int


@dataclass(frozen=True, slots=True)
class FilesDispatchPayload:
    reservation_id: str
    reservation_operation_uuid: str
    expected_reservation_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class FilesReconcileObservationPayload:
    path_digest: str
    outcome: Literal["committed", "no_effect", "unknown"]
    observed_file_version: int
    observed_size_bytes: int
    content_sha256: str | None
    inode_digest: str | None
    confirmed_at: str


@dataclass(frozen=True, slots=True)
class FilesReconcileWritePayload(FilesDispatchPayload):
    observation: FilesReconcileObservationPayload


@dataclass(frozen=True, slots=True)
class FilesConfigureQuotaPayload:
    service_id: str
    instance_uuid: str
    byte_limit: int
    expected_quota_version: int | None


@dataclass(frozen=True, slots=True)
class FilesReservationMutationPayload:
    reservation_id: str
    original_operation_uuid: str
    expected_version: int
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class FilesReservationInspectPayload:
    reservation_id: str
    original_operation_uuid: str
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class FilesMetadataPayload:
    path_digest: str
    service_id: str
    instance_uuid: str


@dataclass(frozen=True, slots=True)
class FilesListIndexPayload:
    after_file_id: str | None
    limit: int
    service_id: str
    instance_uuid: str
