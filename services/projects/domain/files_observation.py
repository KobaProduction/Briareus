"""Immutable native Files observations and their reconciliation binding rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedNativeFilesObservation:
    """Verified by native Files supervisor, not supplied by browser JSON."""

    reservation_id: UUID
    original_operation_uuid: UUID
    project_id: UUID
    service_id: UUID
    instance_uuid: UUID
    path_digest: str
    outcome: Literal["committed", "no_effect", "unknown"]
    observed_file_version: int
    observed_size_bytes: int
    content_sha256: str | None
    inode_digest: str | None
    confirmed_at: datetime

    def matches_reconciliation(
        self,
        *,
        reservation_id: UUID,
        original_operation_uuid: UUID,
        project_id: UUID,
        service_id: UUID,
        instance_uuid: UUID,
    ) -> bool:
        return not (
            self.reservation_id != reservation_id
            or self.original_operation_uuid != original_operation_uuid
            or self.project_id != project_id
            or (self.service_id != service_id)
            or (self.instance_uuid != instance_uuid)
            or (self.observed_file_version < 0)
            or (not 0 <= self.observed_size_bytes <= 100000000000000)
            or (self.confirmed_at.tzinfo is None)
            or (not timedelta(0) <= datetime.now(UTC) - self.confirmed_at <= timedelta(minutes=2))
            or (len(self.path_digest) != 64)
            or any(c not in "0123456789abcdef" for c in self.path_digest)
        )

    def has_valid_optional_digests(self) -> bool:
        for digest in (self.content_sha256, self.inode_digest):
            if digest is not None and (
                len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)
            ):
                return False
        return True
