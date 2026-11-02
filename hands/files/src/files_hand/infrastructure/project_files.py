"""Pinned-descriptor private Files adapter; grants remain with its caller."""

from __future__ import annotations

import base64
import os
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from files_hand.application.private_read import HashPrivateFile, ReadPrivateFile
from files_hand.application.private_receipts import (
    BasicFileEntry,
    PrivateFileEntry,
    PrivateFileHash,
    PrivateFileList,
    PrivateFileRead,
    PrivateFileResult,
)
from files_hand.application.read_file import FileReadSource
from files_hand.domain.chunk_write import FileSnapshot
from files_hand.domain.private_read import (
    ConfinedEntry,
    PrivateFileQuery,
    PrivatePathAction,
    PrivatePathQuery,
    project_components,
    require_private_directory_index,
)
from files_hand.infrastructure.chunk_storage import snapshot
from modules.project_runtime.workspace_roots import ProjectFileError, _open_beneath

TOOLS = frozenset({"file_list", "file_info", "file_read", "file_hash"})
FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


class PrivateDescriptorWorkspace(Protocol):
    def opened(self, path: str) -> AbstractContextManager[tuple[int, os.stat_result]]: ...


@dataclass
class PrivateDescriptorRead:
    descriptor: int
    before: FileSnapshot
    after: FileSnapshot | None = None

    def read(self, offset: int, length: int) -> bytes:
        data = os.pread(self.descriptor, length, offset)
        self.after = snapshot(os.fstat(self.descriptor))
        return data

    def current(self) -> FileSnapshot:
        if self.after is None:
            raise ValueError("File has not been read")
        return self.after


@dataclass(frozen=True)
class PrivateReadStorage:
    workspace: PrivateDescriptorWorkspace

    @contextmanager
    def open(self, path: str) -> Iterator[FileReadSource]:
        with self.workspace.opened(path) as (descriptor, info):
            yield PrivateDescriptorRead(descriptor, snapshot(info))


class ProjectFiles:
    def __init__(self, root: str | Path) -> None:
        self.root = os.open(root, FLAGS | os.O_DIRECTORY)
        self.root_info = os.fstat(self.root)
        if self.root_info.st_uid != os.geteuid() or self.root_info.st_mode & 0o077:
            os.close(self.root)
            raise ValueError("Files project root must be owner-private")

    def close(self) -> None:
        os.close(self.root)

    @contextmanager
    def opened(self, path: str, *, directory: bool = False) -> Iterator[tuple[int, os.stat_result]]:
        parts = project_components(path)
        fd = os.dup(self.root)
        try:
            for index, part in enumerate(parts):
                flags = FLAGS | (os.O_DIRECTORY if directory or index < len(parts) - 1 else 0)
                child = _open_beneath(fd, part, flags)
                os.close(fd)
                fd = child
            info = os.fstat(fd)
            ConfinedEntry(
                info.st_dev,
                info.st_uid,
                info.st_mode,
                stat.S_ISREG(info.st_mode),
                stat.S_ISDIR(info.st_mode),
                info.st_nlink,
            ).require_safe(self.root_info.st_dev, os.geteuid())
            yield fd, info
        finally:
            os.close(fd)

    @staticmethod
    def entry(path: str, info: os.stat_result) -> BasicFileEntry:
        return PrivateFileEntry(
            path,
            path.rsplit("/", 1)[-1],
            "directory" if stat.S_ISDIR(info.st_mode) else "file",
            info.st_size if stat.S_ISREG(info.st_mode) else 0,
        )

    def _list(self, path: str) -> PrivateFileList:
        entries: list[BasicFileEntry] = []
        with self.opened(path, directory=True) as (fd, _), os.scandir(fd) as items:
            for index, item in enumerate(items):
                require_private_directory_index(index)
                candidate = (path + "/" if path else "") + item.name
                try:
                    with self.opened(candidate) as (_, child):
                        entries.append(self.entry(candidate, child))
                except (OSError, ValueError, ProjectFileError):
                    continue
        return PrivateFileList(
            path,
            tuple(
                sorted(entries, key=lambda item: (item.type != "directory", item.name.casefold()))
            ),
        )

    def execute(self, query: PrivateFileQuery) -> PrivateFileResult:
        path = query.path
        if isinstance(query, PrivatePathQuery):
            if query.action is PrivatePathAction.LIST:
                return self._list(path)
            if query.action is PrivatePathAction.INFO:
                with self.opened(path) as (_, info):
                    return self.entry(path, info)
            return PrivateFileHash(path, HashPrivateFile(PrivateReadStorage(self)).execute(path))
        storage = PrivateReadStorage(self)
        page = ReadPrivateFile(storage).execute(path, query.window)
        return PrivateFileRead(
            page.path, base64.b64encode(page.data).decode("ascii"), page.offset, page.size_bytes
        )
