"""Bounded read/hash use cases for the existing private descriptor endpoint."""

import hashlib

from files_hand.domain.file_read import require_stable_read
from files_hand.domain.private_read import PrivateReadWindow, require_private_file

from ._storage_binding import _StorageBinding
from .read_file import FilePage, FileReadStorage


class ReadPrivateFile(_StorageBinding[FileReadStorage]):
    def execute(self, path: str, window: PrivateReadWindow) -> FilePage:
        with self._storage.open(path) as source:
            before = source.before
            require_private_file(before)
            data = source.read(window.offset, window.length)
            require_stable_read(before, source.current())
            return FilePage(path, window.offset, data, before.size_bytes)


class HashPrivateFile(_StorageBinding[FileReadStorage]):
    def execute(self, path: str) -> str:
        with self._storage.open(path) as source:
            before = source.before
            require_private_file(before)
            data = source.read(0, 262_145)
            require_stable_read(before, source.current())
            if len(data) > 262_144:
                raise ValueError("File changed during bounded read")
            return hashlib.sha256(data).hexdigest()
