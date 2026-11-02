"""Legacy workspace upload staging pinned to a real parent descriptor."""

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from project_runtime_client.domain.workspace import ProjectFileError
from project_runtime_client.files.application.ingest_attachment import (
    AttachmentSink,
    AttachmentTarget,
)
from project_runtime_client.files.domain.receipts import WorkspaceIngestReceipt
from project_runtime_client.files.workspace import _rename_no_replace
from project_runtime_client.workspace_compat.domain.receipts import WorkspaceFileEntry
from project_runtime_client.workspace_compat.domain.transfers import WorkspaceFileError
from project_runtime_client.workspace_compat.infrastructure.filesystem import WorkspaceFileStore


@contextmanager
def pinned_parent(root: Path, parent: Path) -> Iterator[int]:
    relative = parent.relative_to(root)
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
    fd = os.open(root, flags)
    try:
        for part in relative.parts:
            with suppress(FileExistsError):
                os.mkdir(part, 0o700, dir_fd=fd)
            child = os.open(part, flags, dir_fd=fd)
            os.close(fd)
            fd = child
        yield fd
    finally:
        os.close(fd)


@dataclass(frozen=True)
class BufferedAttachmentSink:
    handle: BinaryIO

    def write(self, data: bytes) -> None:
        self.handle.write(data)

    def flush(self) -> None:
        self.handle.flush()
        os.fsync(self.handle.fileno())


@dataclass(frozen=True)
class PinnedAttachmentTarget:
    workspace: WorkspaceFileStore
    path: Path
    parent: int
    temporary: str
    destination: str
    overwrite: bool

    @contextmanager
    def writing(self) -> Iterator[AttachmentSink]:
        fd = os.open(
            self.temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
            0o600,
            dir_fd=self.parent,
        )
        with os.fdopen(fd, "wb") as handle:
            yield BufferedAttachmentSink(handle)

    def commit(self) -> None:
        if self.overwrite:
            os.replace(
                self.temporary, self.path.name, src_dir_fd=self.parent, dst_dir_fd=self.parent
            )
        else:
            try:
                _rename_no_replace(self.parent, self.temporary, self.parent, self.path.name)
            except ProjectFileError as exc:
                if exc.code == "FILE_EXISTS":
                    raise WorkspaceFileError(
                        f"destination already exists: {self.destination}"
                    ) from exc
                raise WorkspaceFileError("atomic attachment placement unavailable") from exc
        try:
            os.fsync(self.parent)
        except OSError as exc:
            raise WorkspaceFileError("attachment commit outcome uncertain") from exc

    def receipt(self, digest: str) -> WorkspaceIngestReceipt:
        entry = self.workspace.info(self.workspace.relative(self.path))
        if not isinstance(entry, WorkspaceFileEntry):
            raise WorkspaceFileError("attachment destination is no longer a regular file")
        return WorkspaceIngestReceipt(
            path=entry.path,
            name=entry.name,
            size_bytes=entry.size_bytes,
            modified_at_ns=entry.modified_at_ns,
            mime_type=entry.mime_type,
            sha256=digest,
        )


class WorkspaceAttachmentStorage:
    def __init__(self, workspace: WorkspaceFileStore, path: Path) -> None:
        self._workspace, self._path = workspace, path

    @contextmanager
    def target(self, destination: str, overwrite: bool) -> Iterator[AttachmentTarget]:
        with pinned_parent(self._workspace.root, self._path.parent) as parent:
            temporary = f".{self._path.name}.upload-{uuid.uuid4().hex}.part"
            try:
                yield PinnedAttachmentTarget(
                    self._workspace, self._path, parent, temporary, destination, overwrite
                )
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=parent)
