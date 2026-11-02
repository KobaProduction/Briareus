"""Verified immutable source and native import observations and their binding rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID


@dataclass(frozen=True, slots=True)
class VerifiedFilesSourceReceipt:
    project_id: UUID
    file_object_id: UUID
    file_version: int
    content_sha256: str
    size_bytes: int
    source_revision: str
    confirmed_at: datetime

    def matches_source(self, *, project_id: UUID, file_object_id: UUID) -> bool:
        return not (
            self.project_id != project_id
            or self.file_object_id != file_object_id
            or self.file_version < 1
            or (not 0 <= self.size_bytes <= 100000000000000)
            or (len(self.content_sha256) != 64)
            or any(c not in "0123456789abcdef" for c in self.content_sha256)
            or (self.confirmed_at.tzinfo is None)
        )


@dataclass(frozen=True, slots=True)
class VerifiedNativeImportObservation:
    import_uuid: UUID
    original_operation_uuid: UUID
    project_id: UUID
    native_project_id: UUID
    file_object_id: UUID
    owner_service_id: UUID
    outcome: Literal["succeeded", "confirmed_absent", "unknown"]
    native_artifact_id: str | None
    result_sha256: str | None
    observed_at: datetime
    native_scope_digest: str

    def matches_import(
        self,
        *,
        import_uuid: UUID,
        original_operation_uuid: UUID,
        project_id: UUID,
        service_id: UUID,
    ) -> bool:
        return not (
            self.import_uuid != import_uuid
            or self.original_operation_uuid != original_operation_uuid
            or self.project_id != project_id
            or (self.owner_service_id != service_id)
            or (self.observed_at.tzinfo is None)
            or (self.observed_at > datetime.now(UTC))
            or (datetime.now(UTC) - self.observed_at > timedelta(minutes=2))
            or (len(self.native_scope_digest) != 64)
            or any(c not in "0123456789abcdef" for c in self.native_scope_digest)
        )

    def has_valid_result_identity(self) -> bool:
        return not (
            not self.native_artifact_id
            or len(self.native_artifact_id) > 256
            or self.result_sha256 is None
            or (len(self.result_sha256) != 64)
            or any(c not in "0123456789abcdef" for c in self.result_sha256)
        )
