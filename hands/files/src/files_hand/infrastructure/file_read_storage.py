"""Pinned-descriptor read adapter retaining effect freshness checks."""

import os
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol

from files_hand.application.read_file import FileReadSource
from files_hand.domain.chunk_write import FileSnapshot
from files_hand.infrastructure.chunk_storage import snapshot
from service_runtime._runtime_reference_bindings import _WorkspaceBinding


class ReadWorkspace(Protocol):
    def opened(self, path: str) -> AbstractContextManager[tuple[int, os.stat_result]]: ...
    def check(self) -> None: ...


@dataclass
class DescriptorReadSource:
    descriptor: int
    before: FileSnapshot
    workspace: ReadWorkspace
    _after: FileSnapshot | None = None

    def read(self, offset: int, length: int) -> bytes:
        self.workspace.check()
        data = os.pread(self.descriptor, length, offset)
        self._after = snapshot(os.fstat(self.descriptor))
        self.workspace.check()
        return data

    def current(self) -> FileSnapshot:
        if self._after is None:
            raise ValueError("File has not been read")
        return self._after


class WorkspaceReadStorage(_WorkspaceBinding[ReadWorkspace]):
    @contextmanager
    def open(self, path: str) -> Iterator[FileReadSource]:
        with self._workspace.opened(path) as (descriptor, info):
            yield DescriptorReadSource(descriptor, snapshot(info), self._workspace)
