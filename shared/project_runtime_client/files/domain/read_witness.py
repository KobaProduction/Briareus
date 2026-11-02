"""File/native observation equality and five-second witness freshness."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID


class ReadWitnessChanged(ValueError):
    """The trusted observation no longer binds this read."""


@dataclass(frozen=True, slots=True)
class FileContentBinding:
    project_uuid: UUID
    path_digest: str
    size_bytes: int
    content_sha256: str


@dataclass(frozen=True, slots=True)
class NativeReadBinding:
    operation_uuid: UUID
    project_uuid: UUID
    file_uuid: UUID
    agent_session_uuid: UUID
    actor_uuid: UUID
    service_uuid: UUID
    instance_uuid: UUID
    path_digest: str
    file_version: int
    size_bytes: int
    content_sha256: str
    inode_digest: str


@dataclass(frozen=True, slots=True)
class ReadWitnessExpectation:
    file: FileContentBinding
    native: NativeReadBinding


@dataclass(frozen=True, slots=True)
class ReadWitnessObservation:
    file: FileContentBinding
    native: NativeReadBinding
    observed_at: datetime
    recipient_expires_at: datetime


def require_current_witness(
    expected: ReadWitnessExpectation, observed: ReadWitnessObservation, now: datetime
) -> None:
    if (
        expected.file != observed.file
        or expected.native != observed.native
        or not timedelta(0) <= now - observed.observed_at <= timedelta(seconds=5)
        or observed.recipient_expires_at <= now
    ):
        raise ReadWitnessChanged("A14_FILES_NATIVE_READ_SCOPE_CHANGED")
