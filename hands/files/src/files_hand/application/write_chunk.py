"""Publish a chunk only after preserving the exact observed append prefix."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from files_hand.domain.chunk_write import FileSnapshot, require_chunk_size, require_chunk_target

from ._storage_binding import _StorageBinding


@dataclass(frozen=True, slots=True)
class ChunkWrite:
    path: str
    data: bytes
    offset: int
    truncate: bool
    create_parents: bool
    max_file_bytes: int

    def __post_init__(self) -> None:
        require_chunk_size(
            self.offset, len(self.data), truncate=self.truncate, max_file_bytes=self.max_file_bytes
        )


@dataclass(frozen=True, slots=True)
class ChunkWriteReceipt:
    path: str
    bytes_written: int
    next_offset: int
    size_bytes: int


class ChunkStage(Protocol):
    def existing(self) -> FileSnapshot | None: ...
    def copy_prefix(self, before: FileSnapshot, length: int) -> None: ...
    def write(self, data: bytes) -> None: ...
    def publish(self, before: FileSnapshot | None) -> None: ...


class ChunkStorage(Protocol):
    def stage(self, path: str, *, create_parents: bool) -> AbstractContextManager[ChunkStage]: ...


class WriteChunk(_StorageBinding[ChunkStorage]):
    def execute(self, command: ChunkWrite) -> ChunkWriteReceipt:
        with self._storage.stage(command.path, create_parents=command.create_parents) as stage:
            before = stage.existing()
            require_chunk_target(command.offset, truncate=command.truncate, before=before)
            if not command.truncate and before is not None:
                stage.copy_prefix(before, command.offset)
            stage.write(command.data)
            stage.publish(before)
        size = command.offset + len(command.data)
        return ChunkWriteReceipt(command.path, len(command.data), size, size)
