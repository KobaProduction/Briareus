"""Read a single stable page through an authority-aware source port."""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from files_hand.domain.chunk_write import FileSnapshot
from files_hand.domain.file_read import FileReadWindow, require_stable_read

from ._storage_binding import _StorageBinding


class FileReadSource(Protocol):
    @property
    def before(self) -> FileSnapshot: ...
    def read(self, offset: int, length: int) -> bytes: ...
    def current(self) -> FileSnapshot: ...


class FileReadStorage(Protocol):
    def open(self, path: str) -> AbstractContextManager[FileReadSource]: ...


@dataclass(frozen=True)
class FilePage:
    path: str
    offset: int
    data: bytes
    size_bytes: int

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.data)

    @property
    def eof(self) -> bool:
        return self.next_offset >= self.size_bytes


class ReadFile(_StorageBinding[FileReadStorage]):
    def execute(self, path: str, window: FileReadWindow) -> FilePage:
        with self._storage.open(path) as source:
            before = source.before
            window.require_readable(before)
            data = source.read(window.offset, window.page_bytes)
            require_stable_read(before, source.current())
            return FilePage(path, window.offset, data, before.size_bytes)
