"""Original Files workspace API over pinned descriptors, never raw host paths."""

from __future__ import annotations

import base64
import hashlib
import os
import stat
import time
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from uuid import uuid4

from modules.files.models import ClientFile
from modules.files.project_workspace import _checked_entry, _components, _rename_no_replace
from modules.files.workspace_store import WorkspaceFileStore
from modules.project_runtime.workspace_roots import ProjectFileError, _open_beneath
from modules.workspace_compat.domain.receipts import (
    WorkspaceAbsent,
    WorkspaceDelete,
    WorkspaceDeleted,
    WorkspaceDirectoryEntry,
    WorkspaceRead,
    WorkspaceStatus,
)

from ._project_files import FLAGS, ProjectFiles
from .application.workspace_receipts import (
    FileDirectoryPage,
    FileEntry,
    NodeFileEntry,
    NodeIngestReceipt,
)
from .application.write_chunk import ChunkWrite, ChunkWriteReceipt, WriteChunk
from .domain.chunk_write import MAX_FILE_BYTES
from .domain.workspace_tree import TreeTraversalBudget, require_separate_destination
from .infrastructure.chunk_storage import WorkspaceChunkStorage

MAX_BYTES = MAX_FILE_BYTES
MAX_ENTRIES = 10_000
_deadline = ContextVar("files_node_deadline", default=0.0)


class NodeWorkspace(ProjectFiles):
    @contextmanager
    def authority(self, expires_at: float) -> Iterator[None]:
        token = _deadline.set(expires_at)
        try:
            self.check()
            yield
            self.check()
        finally:
            _deadline.reset(token)

    @staticmethod
    def check() -> None:
        if time.time() >= _deadline.get():
            raise ValueError("Files execution authority expired")

    def components(self, path: str, *, root_allowed: bool = False) -> tuple[str, ...]:
        self.check()
        if not unicodedata.is_normalized("NFC", path):
            raise ValueError("Canonical relative path required")
        parts = _components(path, root_allowed=root_allowed)
        if any(part.startswith(".briareus-stage-") for part in parts):
            raise ValueError("Private Files staging name is reserved")
        return parts

    def checked(self, info: os.stat_result) -> None:
        self.check()
        _checked_entry(info, device=self.root_info.st_dev)

    @contextmanager
    def parent(self, path: str, *, create: bool = False) -> Iterator[tuple[int, str]]:
        parts = self.components(path)
        fd = os.dup(self.root)
        try:
            for part in parts[:-1]:
                self.check()
                if create:
                    with suppress(FileExistsError):
                        os.mkdir(part, 0o700, dir_fd=fd)
                child = _open_beneath(fd, part, FLAGS | os.O_DIRECTORY)
                self.checked(os.fstat(child))
                os.close(fd)
                fd = child
            yield fd, parts[-1]
        finally:
            os.close(fd)

    @staticmethod
    def entry(path: str, info: os.stat_result) -> FileEntry:
        name = path.rsplit("/", 1)[-1]
        if stat.S_ISDIR(info.st_mode):
            return WorkspaceDirectoryEntry(path, name, 0, info.st_mtime_ns)
        return NodeFileEntry(path, name, info.st_size, info.st_mtime_ns)

    def status(self) -> WorkspaceStatus:
        self.check()
        usage = os.fstatvfs(self.root)
        return WorkspaceStatus(
            "/",
            usage.f_bavail * usage.f_frsize,
            (usage.f_blocks - usage.f_bfree) * usage.f_frsize,
            usage.f_blocks * usage.f_frsize,
        )

    def info(self, path: str) -> FileEntry:
        self.components(path)
        with self.opened(path) as (_, info):
            return self.entry(path, info)

    def list(self, path: str = "", *, offset: int = 0, limit: int = 200) -> FileDirectoryPage:
        self.components(path, root_allowed=True)
        if (
            type(offset) is not int
            or offset < 0
            or type(limit) is not int
            or not 1 <= limit <= 1000
        ):
            raise ValueError("Bounded directory page required")
        result = []
        with self.opened(path, directory=True) as (fd, _), os.scandir(fd) as entries:
            for index, item in enumerate(entries):
                self.check()
                if index >= MAX_ENTRIES:
                    raise ValueError("Directory page capacity exceeded")
                if item.name.startswith(".briareus-stage-"):
                    continue
                child_path = path + "/" + item.name if path else item.name
                try:
                    with self.opened(child_path) as (_, info):
                        result.append(self.entry(child_path, info))
                except (OSError, ValueError, ProjectFileError):
                    continue
        result.sort(key=lambda item: (item.type != "directory", item.name.casefold()))
        selected = result[offset : offset + limit]
        return FileDirectoryPage(
            path or "/",
            tuple(selected),
            len(selected),
            len(result),
            offset,
            limit,
            offset + len(selected) < len(result),
        )

    def read(self, path: str, *, offset: int = 0, length: int = 1024 * 1024) -> WorkspaceRead:
        from .application.read_file import ReadFile
        from .domain.file_read import FileReadWindow
        from .infrastructure.file_read_storage import WorkspaceReadStorage

        self.components(path)
        page = ReadFile(WorkspaceReadStorage(self)).execute(path, FileReadWindow(offset, length))
        return WorkspaceRead(
            page.path,
            page.offset,
            len(page.data),
            page.next_offset,
            page.size_bytes,
            page.eof,
            base64.b64encode(page.data).decode("ascii"),
        )

    def sha256(self, path: str) -> str:
        self.components(path)
        with self.opened(path) as (fd, before):
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES:
                raise ValueError("Bounded regular file required")
            digest = hashlib.sha256()
            offset = 0
            while offset < before.st_size:
                self.check()
                data = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
                if not data:
                    raise ValueError("File shortened during hash")
                digest.update(data)
                offset += len(data)
            if self.signature(before) != self.signature(os.fstat(fd)):
                raise ValueError("File changed during hash")
            self.check()
            return digest.hexdigest()

    @staticmethod
    def signature(info: os.stat_result) -> tuple[int, int, int, int, int]:
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def existing(self, parent: int, name: str) -> os.stat_result | None:
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        self.checked(info)
        return info

    def commit(self, parent: int, temporary: str, name: str, *, overwrite: bool) -> None:
        self.check()
        previous = self.existing(parent, name)
        if previous is not None and not overwrite:
            raise ValueError("Destination exists")
        if overwrite:
            os.replace(temporary, name, src_dir_fd=parent, dst_dir_fd=parent)
        else:
            _rename_no_replace(parent, temporary, parent, name)
        os.fsync(parent)

    @contextmanager
    def staged(self, parent: int) -> Iterator[tuple[str, int]]:
        name = ".briareus-stage-" + uuid4().hex
        fd = os.open(
            name,
            os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=parent,
        )
        try:
            yield name, fd
        finally:
            os.close(fd)
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=parent)

    def write_bytes(self, fd: int, data: bytes) -> None:
        view = memoryview(data)
        while view:
            self.check()
            written = os.write(fd, view[: 1024 * 1024])
            if written <= 0:
                raise ValueError("File write did not progress")
            view = view[written:]

    def write_text(
        self, path: str, content: str, *, overwrite: bool = True, create_parents: bool = True
    ) -> FileEntry:
        data = content.encode("utf-8")
        if len(data) > MAX_BYTES:
            raise ValueError("Text exceeds file budget")
        with (
            self.parent(path, create=create_parents) as (parent, name),
            self.staged(parent) as (temporary, fd),
        ):
            self.write_bytes(fd, data)
            os.fsync(fd)
            self.commit(parent, temporary, name, overwrite=overwrite)
        return self.info(path)

    def write_chunk(
        self,
        path: str,
        data_base64: str,
        *,
        offset: int = 0,
        truncate: bool = False,
        create_parents: bool = True,
        max_file_bytes: int = MAX_BYTES,
    ) -> ChunkWriteReceipt:
        command = ChunkWrite(
            path,
            base64.b64decode(data_base64, validate=True),
            offset,
            truncate,
            create_parents,
            max_file_bytes,
        )
        return WriteChunk(WorkspaceChunkStorage(self, _open_beneath, FLAGS)).execute(command)

    def mkdir(self, path: str, *, parents: bool = True) -> FileEntry:
        with self.parent(path, create=parents) as (parent, name):
            self.check()
            with suppress(FileExistsError):
                os.mkdir(name, 0o700, dir_fd=parent)
            child = _open_beneath(parent, name, FLAGS | os.O_DIRECTORY)
            try:
                self.checked(os.fstat(child))
            finally:
                os.close(child)
            os.fsync(parent)
        return self.info(path)

    def _remove(
        self,
        parent: int,
        name: str,
        *,
        recursive: bool,
        budget: TreeTraversalBudget,
        depth: int = 0,
    ) -> bool:
        self.check()
        budget.visit(depth)
        info = self.existing(parent, name)
        if info is None:
            return False
        if stat.S_ISDIR(info.st_mode):
            child = _open_beneath(parent, name, FLAGS | os.O_DIRECTORY)
            try:
                self.checked(os.fstat(child))
                if recursive:
                    with os.scandir(child) as entries:
                        for item in entries:
                            self._remove(
                                child, item.name, recursive=True, budget=budget, depth=depth + 1
                            )
                self.check()
                os.rmdir(name, dir_fd=parent)
            finally:
                os.close(child)
        else:
            self.check()
            os.unlink(name, dir_fd=parent)
        os.fsync(parent)
        return True

    def delete(self, path: str, *, recursive: bool = False) -> WorkspaceDelete:
        with self.parent(path) as (parent, name):
            deleted = self._remove(parent, name, recursive=recursive, budget=TreeTraversalBudget())
        return WorkspaceDeleted(path) if deleted else WorkspaceAbsent(path)

    def _copy(
        self,
        source_parent: int,
        source_name: str,
        target_parent: int,
        target_name: str,
        budget: TreeTraversalBudget,
        depth: int = 0,
    ) -> None:
        self.check()
        budget.visit(depth)
        source = _open_beneath(source_parent, source_name, FLAGS)
        try:
            before = os.fstat(source)
            self.checked(before)
            if stat.S_ISDIR(before.st_mode):
                self._copy_directory(source, target_parent, target_name, budget, depth)
            else:
                self._copy_regular(source, before, target_parent, target_name)
        finally:
            os.close(source)

    def _copy_directory(
        self,
        source: int,
        target_parent: int,
        target_name: str,
        budget: TreeTraversalBudget,
        depth: int,
    ) -> None:
        os.mkdir(target_name, 0o700, dir_fd=target_parent)
        target = _open_beneath(target_parent, target_name, FLAGS | os.O_DIRECTORY)
        try:
            with os.scandir(source) as entries:
                for item in entries:
                    self.components(item.name)
                    self._copy(source, item.name, target, item.name, budget, depth + 1)
            self.check()
            os.fsync(target)
        finally:
            os.close(target)

    def _copy_regular(
        self, source: int, before: os.stat_result, target_parent: int, target_name: str
    ) -> None:
        if before.st_size > MAX_BYTES:
            raise ValueError("Copy exceeds configured file limit")
        target = os.open(
            target_name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=target_parent,
        )
        try:
            offset = 0
            while offset < before.st_size:
                self.check()
                data = os.pread(source, min(1024 * 1024, before.st_size - offset), offset)
                if not data:
                    raise ValueError("Copy source shortened")
                self.write_bytes(target, data)
                offset += len(data)
            if self.signature(before) != self.signature(os.fstat(source)):
                raise ValueError("Copy source changed")
            os.fsync(target)
        finally:
            os.close(target)

    def copy(self, source: str, destination: str, *, overwrite: bool = False) -> FileEntry:
        self.components(source)
        self.components(destination)
        require_separate_destination(source, destination)
        with (
            self.parent(source) as (source_parent, source_name),
            self.parent(destination, create=True) as (target_parent, target_name),
        ):
            if self.existing(target_parent, target_name) is not None and not overwrite:
                raise ValueError("Destination exists")
            temporary = ".briareus-stage-" + uuid4().hex
            try:
                self._copy(
                    source_parent, source_name, target_parent, temporary, TreeTraversalBudget()
                )
                if overwrite and self.existing(target_parent, target_name) is not None:
                    self._remove(
                        target_parent, target_name, recursive=True, budget=TreeTraversalBudget()
                    )
                self.commit(target_parent, temporary, target_name, overwrite=False)
            finally:
                # Cleanup only the unique staging name; never follow a symlink
                # or continue a user mutation after its authority expired.
                if time.time() < _deadline.get():
                    with suppress(FileNotFoundError):
                        self._remove(
                            target_parent, temporary, recursive=True, budget=TreeTraversalBudget()
                        )
        return self.info(destination)

    def move(self, source: str, destination: str, *, overwrite: bool = False) -> FileEntry:
        self.components(source)
        self.components(destination)
        require_separate_destination(source, destination)
        with (
            self.parent(source) as (source_parent, source_name),
            self.parent(destination, create=True) as (target_parent, target_name),
        ):
            if self.existing(source_parent, source_name) is None:
                raise ValueError("Move source not found")
            if overwrite and self.existing(target_parent, target_name) is not None:
                self._remove(
                    target_parent, target_name, recursive=True, budget=TreeTraversalBudget()
                )
            self.check()
            _rename_no_replace(source_parent, source_name, target_parent, target_name)
            os.fsync(source_parent)
            os.fsync(target_parent)
        return self.info(destination)

    def ingest(
        self,
        *,
        file: ClientFile,
        destination: str,
        expected_size: int | None = None,
        expected_sha256: str = "",
        overwrite: bool = False,
        workspace: NodeWorkspace | WorkspaceFileStore | None = None,
        max_bytes: int | None = None,
    ) -> NodeIngestReceipt:
        from modules.files._attachment_transport import validate_public_attachment_url
        from modules.files.workspace_ingress import _validate_sha256

        from .application.ingest_attachment import IngestAttachment
        from .domain.attachment import AttachmentExpectation
        from .infrastructure.attachment_storage import WorkspaceAttachmentStorage

        # Compatibility callback parameters never select the descriptor root or its budget.
        del workspace, max_bytes
        self.check()
        validate_public_attachment_url(file.download_url)
        expected = AttachmentExpectation(expected_size, _validate_sha256(expected_sha256))
        receipt = IngestAttachment(WorkspaceAttachmentStorage(self, _deadline.get())).execute(
            file.download_url,
            destination,
            overwrite,
            expected,
        )
        entry = self.info(destination)
        if not isinstance(entry, NodeFileEntry):
            raise ValueError("Attachment destination is no longer a regular file")
        return NodeIngestReceipt(
            path=entry.path,
            name=entry.name,
            size_bytes=entry.size_bytes,
            modified_at_ns=entry.modified_at_ns,
            sha256=receipt.sha256,
        )
