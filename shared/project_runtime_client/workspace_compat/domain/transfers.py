"""Bounds and append consistency of the historical workspace protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Self


class WorkspaceFileError(RuntimeError):
    """Workspace filesystem operation failed."""


def require_offset(offset: int) -> None:
    if offset < 0:
        raise WorkspaceFileError("offset must be >= 0")


@dataclass(frozen=True, slots=True)
class WorkspaceListWindow:
    offset: int
    limit: int

    def __post_init__(self) -> None:
        require_offset(self.offset)
        if not 1 <= self.limit <= 1000:
            raise WorkspaceFileError("limit must be between 1 and 1000")


@dataclass(frozen=True, slots=True)
class WorkspaceReadWindow:
    offset: int
    length: int

    def __post_init__(self) -> None:
        require_offset(self.offset)
        if not 1 <= self.length <= 16 * 1024 * 1024:
            raise WorkspaceFileError("length must be between 1 and 16777216")

    def require_size(self, size: int) -> None:
        if self.offset > size:
            raise WorkspaceFileError("offset exceeds file size")


@dataclass(frozen=True, slots=True)
class WorkspaceAppendPlan:
    current_size: int
    next_offset: int

    @classmethod
    def prepare(
        cls,
        *,
        current_size: int,
        byte_count: int,
        offset: int,
        truncate: bool,
        max_file_bytes: int,
    ) -> Self:
        if truncate:
            if offset != 0:
                raise WorkspaceFileError("truncate=true requires offset=0")
            current_size = 0
        elif offset != current_size:
            raise WorkspaceFileError(f"offset mismatch: expected {current_size}, received {offset}")
        next_offset = current_size + byte_count
        if next_offset > max_file_bytes:
            raise WorkspaceFileError("file exceeds configured size limit")
        return cls(current_size, next_offset)


class EarlyOffsetWorkspaceAppendPlan(WorkspaceAppendPlan):
    @classmethod
    def prepare(
        cls,
        *,
        current_size: int,
        byte_count: int,
        offset: int,
        truncate: bool,
        max_file_bytes: int,
    ) -> Self:
        require_offset(offset)
        return super().prepare(
            current_size=current_size,
            byte_count=byte_count,
            offset=offset,
            truncate=truncate,
            max_file_bytes=max_file_bytes,
        )
