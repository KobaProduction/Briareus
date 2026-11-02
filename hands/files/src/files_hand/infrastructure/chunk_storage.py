"""Atomic staged append adapter retaining descriptor and authority checks."""

import os
import stat
from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from typing import Protocol

from files_hand.application.write_chunk import ChunkStage
from files_hand.domain.chunk_write import FileSnapshot


class DescriptorWorkspace(Protocol):
    def parent(self, path: str, *, create: bool) -> AbstractContextManager[tuple[int, str]]: ...
    def staged(self, parent: int) -> AbstractContextManager[tuple[str, int]]: ...
    def existing(self, parent: int, name: str) -> os.stat_result | None: ...
    def check(self) -> None: ...
    def write_bytes(self, descriptor: int, data: bytes) -> None: ...
    def commit(self, parent: int, temporary: str, name: str, *, overwrite: bool) -> None: ...


def snapshot(info: os.stat_result) -> FileSnapshot:
    return FileSnapshot(
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns),
        info.st_size,
        stat.S_ISREG(info.st_mode),
    )


@dataclass
class DescriptorChunkStage:
    workspace: DescriptorWorkspace
    parent: int
    name: str
    temporary: str
    descriptor: int
    open_beneath: Callable[[int, str, int], int]
    read_flags: int

    def existing(self) -> FileSnapshot | None:
        info = self.workspace.existing(self.parent, self.name)
        return snapshot(info) if info is not None else None

    def copy_prefix(self, before: FileSnapshot, length: int) -> None:
        source = self.open_beneath(self.parent, self.name, self.read_flags)
        try:
            if before.signature != snapshot(os.fstat(source)).signature:
                raise ValueError("File changed before append")
            self._copy(source, length)
            if before.signature != snapshot(os.fstat(source)).signature:
                raise ValueError("File changed during append")
        finally:
            os.close(source)

    def _copy(self, source: int, length: int) -> None:
        position = 0
        while position < length:
            self.workspace.check()
            chunk = os.pread(source, min(1024 * 1024, length - position), position)
            if not chunk:
                raise ValueError("File changed during append")
            self.workspace.write_bytes(self.descriptor, chunk)
            position += len(chunk)

    def write(self, data: bytes) -> None:
        self.workspace.write_bytes(self.descriptor, data)
        os.fsync(self.descriptor)

    def publish(self, before: FileSnapshot | None) -> None:
        current = self.existing()
        if before is not None and (current is None or before.signature != current.signature):
            raise ValueError("File changed before chunk commit")
        self.workspace.commit(self.parent, self.temporary, self.name, overwrite=before is not None)


class WorkspaceChunkStorage:
    def __init__(
        self,
        workspace: DescriptorWorkspace,
        open_beneath: Callable[[int, str, int], int],
        read_flags: int,
    ) -> None:
        self._workspace = workspace
        self._open_beneath = open_beneath
        self._read_flags = read_flags

    @contextmanager
    def stage(self, path: str, *, create_parents: bool) -> Iterator[ChunkStage]:
        with (
            self._workspace.parent(path, create=create_parents) as (parent, name),
            self._workspace.staged(parent) as (temporary, descriptor),
        ):
            yield DescriptorChunkStage(
                self._workspace,
                parent,
                name,
                temporary,
                descriptor,
                self._open_beneath,
                self._read_flags,
            )
