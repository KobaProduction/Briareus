"""Project Files accounting snapshots and independently observed storage facts."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

ReservationState = Literal["reserved", "dispatched", "committed", "released", "unknown"]


@dataclass(frozen=True, slots=True)
class QuotaSummary:
    project_id: UUID
    byte_limit: int
    used_bytes: int
    reserved_bytes: int
    frozen: bool
    revision: int


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    reservation_id: UUID
    operation_uuid: UUID
    project_id: UUID
    path_digest: str
    expected_content_sha256: str
    project_access_revision: str
    expected_file_version: int
    planned_bytes: int
    reserved_delta: int
    state: str
    revision: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class FilesObservation:
    """Authoritative post-write observation from a VERIFIED Files service.

    Not an upload request DTO. The producer must separately prove its own
    service identity and OS-root provenance under C2 before this can be used
    across processes.
    """

    reservation_id: UUID
    path_digest: str
    observed_file_version: int
    observed_size_bytes: int
    observed_inode_digest: str | None
    confirmed_at: datetime
    confirmed_absent: bool = False
    observed_content_sha256: str | None = None
