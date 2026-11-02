"""Bounds and integrity of a signed public download."""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from owner_protocol.domain.authority import _uuid_v4


class DownloadRejected(Exception):
    pass


class DownloadDigest(Protocol):
    def update(self, data: bytes) -> None: ...
    def hexdigest(self) -> str: ...


def _duration_valid(value: object) -> bool:
    return isinstance(value, (int, float)) and math.isfinite(value) and 0 < value <= 600


def _size_valid(value: object, maximum: int) -> bool:
    return type(value) is int and 0 <= value <= maximum


def _digest_valid(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


@dataclass(frozen=True, slots=True)
class PublicDownload:
    expected_size: int
    expected_sha256: str
    operation_uuid: UUID
    max_seconds: float
    chunk_bytes: int
    maximum_file_bytes: int

    def __post_init__(self) -> None:
        valid = (
            _duration_valid(self.max_seconds)
            and _size_valid(self.chunk_bytes, 262144)
            and self.chunk_bytes > 0
            and _size_valid(self.expected_size, min(self.maximum_file_bytes, 262144))
            and self._operation_valid(self.operation_uuid)
            and _digest_valid(self.expected_sha256)
        )
        if not valid:
            raise DownloadRejected("PROJECT_HTTP_DOWNLOAD_INVALID")

    _operation_valid = staticmethod(_uuid_v4)

    def require_content_length(self, lengths: tuple[str, ...]) -> None:
        if len(lengths) > 1:
            raise DownloadRejected("PROJECT_HTTP_LENGTH_AMBIGUOUS")
        if not lengths:
            return
        try:
            actual = int(lengths[0])
        except ValueError as exc:
            raise DownloadRejected("PROJECT_HTTP_LENGTH_INVALID") from exc
        if actual != self.expected_size:
            raise DownloadRejected("PROJECT_HTTP_LENGTH_MISMATCH")


@dataclass(slots=True)
class DownloadProgress:
    specification: PublicDownload
    deadline: float
    count: int = 0
    digest: DownloadDigest = field(default_factory=hashlib.sha256)

    def require_time(self, now: float) -> None:
        if now >= self.deadline:
            raise DownloadRejected("PROJECT_HTTP_DEADLINE_EXCEEDED")

    def accept(self, piece: bytes) -> None:
        self.count += len(piece)
        if self.count > self.specification.expected_size:
            raise DownloadRejected("PROJECT_HTTP_TOO_LARGE")
        self.digest.update(piece)

    def finish(self) -> None:
        if (
            self.count != self.specification.expected_size
            or self.digest.hexdigest() != self.specification.expected_sha256
        ):
            raise DownloadRejected("PROJECT_HTTP_CHECKSUM_MISMATCH")
