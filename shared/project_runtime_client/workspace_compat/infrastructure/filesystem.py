"""Shared historical workspace file primitives used by Files, Web and Reverse.

This is byte-compatible legacy workspace behavior, NOT the signed protected
Project Files descriptor-rooted/C2 quota/UID/native owner layer. No Gateway
or owner Runtime may infer a Project grant from these methods.
"""

from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from project_runtime_client.workspace_compat.application.transfers import (
    AppendWorkspaceChunk,
    WorkspaceChunkCommand,
    WorkspaceChunkTarget,
)
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceAbsent,
    WorkspaceDelete,
    WorkspaceDeleted,
    WorkspaceDirectoryEntry,
    WorkspaceEntry,
    WorkspaceFileEntry,
    WorkspacePage,
    WorkspaceRead,
    WorkspaceStatus,
    WorkspaceWrite,
)
from project_runtime_client.workspace_compat.domain.transfers import (
    EarlyOffsetWorkspaceAppendPlan,
    WorkspaceAppendPlan,
    WorkspaceFileError,
    WorkspaceListWindow,
    WorkspaceReadWindow,
    require_offset,
)


@dataclass(frozen=True, slots=True)
class _PathChunkTarget:
    store: WorkspaceFileStore
    target: Path

    def size(self) -> int:
        return self.target.stat().st_size if self.target.exists() else 0

    def append(self, data: bytes, *, truncate: bool) -> None:
        mode = "wb" if truncate or not self.target.exists() else "ab"
        with self.target.open(mode) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())

    def relative_path(self) -> str:
        return self.store.relative(self.target)


class WorkspaceFileStore:
    _append_plan: type[WorkspaceAppendPlan] = EarlyOffsetWorkspaceAppendPlan

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=False)

    def ensure(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, value: str, *, allow_root: bool = False) -> Path:
        self.ensure()
        raw = value.strip().replace("\\", "/")
        if not raw or raw == ".":
            if allow_root:
                return self.root
            raise WorkspaceFileError("path is required")
        if raw.startswith("/"):
            raw = raw.lstrip("/")
        candidate = (self.root / raw).resolve(strict=False)
        if not candidate.is_relative_to(self.root):
            raise WorkspaceFileError("path escapes workspace root")
        if candidate == self.root and not allow_root:
            raise WorkspaceFileError("operation on workspace root is not allowed")
        return candidate

    def relative(self, path: Path) -> str:
        resolved = path.resolve(strict=False)
        if not resolved.is_relative_to(self.root):
            raise WorkspaceFileError("path escapes workspace root")
        value = resolved.relative_to(self.root).as_posix()
        return value if value else "/"

    def status(self) -> WorkspaceStatus:
        self.ensure()
        usage = shutil.disk_usage(self.root)
        return WorkspaceStatus(str(self.root), usage.free, usage.used, usage.total)

    @staticmethod
    def _entry(path: Path, root: Path) -> WorkspaceEntry:
        stat = path.stat()
        relative = path.relative_to(root).as_posix()
        if path.is_dir():
            return WorkspaceDirectoryEntry(relative, path.name, 0, stat.st_mtime_ns)
        return WorkspaceFileEntry(
            relative,
            path.name,
            stat.st_size,
            stat.st_mtime_ns,
            mimetypes.guess_type(path.name)[0] or "",
        )

    def list(self, path: str = "", *, offset: int = 0, limit: int = 200) -> WorkspacePage:
        WorkspaceListWindow(offset, limit)
        directory = self._path(path, allow_root=True)
        if not directory.is_dir():
            raise WorkspaceFileError(f"directory not found: {path or '/'}")
        entries = sorted(
            (item for item in directory.iterdir() if not item.is_symlink()),
            key=lambda item: (not item.is_dir(), item.name.casefold()),
        )
        selected = tuple(self._entry(item, self.root) for item in entries[offset : offset + limit])
        return WorkspacePage(
            self.relative(directory),
            selected,
            len(selected),
            len(entries),
            offset,
            limit,
            offset + len(selected) < len(entries),
        )

    def info(self, path: str) -> WorkspaceEntry:
        target = self._path(path)
        if not target.exists():
            raise WorkspaceFileError(f"path not found: {path}")
        return self._entry(target, self.root)

    def read(self, path: str, *, offset: int = 0, length: int = 1024 * 1024) -> WorkspaceRead:
        window = WorkspaceReadWindow(offset, length)
        target = self._path(path)
        if not target.is_file():
            raise WorkspaceFileError(f"file not found: {path}")
        size = target.stat().st_size
        window.require_size(size)
        with target.open("rb") as handle:
            handle.seek(offset)
            data = handle.read(length)
        next_offset = offset + len(data)
        return WorkspaceRead(
            self.relative(target),
            offset,
            len(data),
            next_offset,
            size,
            next_offset >= size,
            base64.b64encode(data).decode("ascii"),
        )

    def prepare_chunk(self, path: str, *, create_parents: bool) -> WorkspaceChunkTarget:
        target = self._path(path)
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.is_dir():
            raise WorkspaceFileError("parent directory does not exist")
        return _PathChunkTarget(self, target)

    def write_chunk(
        self,
        path: str,
        data_base64: str,
        *,
        offset: int = 0,
        truncate: bool = False,
        create_parents: bool = True,
        max_file_bytes: int,
    ) -> WorkspaceWrite:
        require_offset(offset)
        try:
            data = base64.b64decode(data_base64, validate=True)
        except Exception as exc:
            raise WorkspaceFileError("data_base64 is not valid base64") from exc
        return AppendWorkspaceChunk(self, self._append_plan).execute(
            WorkspaceChunkCommand(
                path,
                data,
                offset,
                truncate,
                create_parents,
                max_file_bytes,
            )
        )

    def write_text(
        self,
        path: str,
        content: str,
        *,
        overwrite: bool = True,
        create_parents: bool = True,
    ) -> WorkspaceEntry:
        target = self._path(path)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"path already exists: {path}")
        if create_parents:
            target.parent.mkdir(parents=True, exist_ok=True)
        elif not target.parent.is_dir():
            raise WorkspaceFileError("parent directory does not exist")
        target.write_text(content, encoding="utf-8")
        return self.info(self.relative(target))

    def mkdir(self, path: str, *, parents: bool = True) -> WorkspaceEntry:
        target = self._path(path)
        target.mkdir(parents=parents, exist_ok=True)
        return self.info(self.relative(target))

    def copy(self, source: str, destination: str, *, overwrite: bool = False) -> WorkspaceEntry:
        src = self._path(source)
        dst = self._path(destination)
        if not src.exists():
            raise WorkspaceFileError(f"source not found: {source}")
        if src.is_dir() and dst.is_relative_to(src):
            raise WorkspaceFileError("destination may not be inside source directory")
        if dst.exists():
            if not overwrite:
                raise WorkspaceFileError(f"destination already exists: {destination}")
            self.delete(destination, recursive=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        if src.is_dir():
            shutil.copytree(src, dst)
        else:
            shutil.copy2(src, dst)
        return self.info(self.relative(dst))

    def move(self, source: str, destination: str, *, overwrite: bool = False) -> WorkspaceEntry:
        src = self._path(source)
        dst = self._path(destination)
        if not src.exists():
            raise WorkspaceFileError(f"source not found: {source}")
        if src.is_dir() and dst.is_relative_to(src):
            raise WorkspaceFileError("destination may not be inside source directory")
        if dst.exists():
            if not overwrite:
                raise WorkspaceFileError(f"destination already exists: {destination}")
            self.delete(destination, recursive=True)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return self.info(self.relative(dst))

    def delete(self, path: str, *, recursive: bool = False) -> WorkspaceDelete:
        target = self._path(path)
        if not target.exists():
            return WorkspaceAbsent(self.relative(target))
        if target.is_dir():
            if not recursive:
                try:
                    target.rmdir()
                except OSError as exc:
                    raise WorkspaceFileError("directory is not empty; use recursive=true") from exc
            else:
                shutil.rmtree(target)
        else:
            target.unlink()
        return WorkspaceDeleted(path.strip().lstrip("/"))

    def put_stream(
        self,
        stream: BinaryIO,
        destination: str,
        *,
        overwrite: bool = False,
    ) -> WorkspaceEntry:
        target = self._path(destination)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"destination already exists: {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (f".{target.name}.upload-{uuid.uuid4().hex}.part")
        try:
            with temporary.open("wb") as handle:
                shutil.copyfileobj(stream, handle, length=1024 * 1024)
                handle.flush()
                os.fsync(handle.fileno())
            if target.exists() and not overwrite:
                raise WorkspaceFileError(f"destination already exists: {destination}")
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return self.info(self.relative(target))

    def place_file(
        self,
        source: Path,
        destination: str,
        *,
        overwrite: bool = False,
        consume: bool = False,
    ) -> WorkspaceEntry:
        target = self._path(destination)
        if target.exists() and not overwrite:
            raise WorkspaceFileError(f"destination already exists: {destination}")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.parent / (f".{target.name}.place-{uuid.uuid4().hex}.part")
        try:
            shutil.copy2(source, temporary)
            if target.exists() and not overwrite:
                raise WorkspaceFileError(f"destination already exists: {destination}")
            os.replace(temporary, target)
            if consume:
                source.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        return self.info(self.relative(target))

    def sha256(self, path: str) -> str:
        target = self._path(path)
        if not target.is_file():
            raise WorkspaceFileError(f"file not found: {path}")
        digest = hashlib.sha256()
        with target.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def target_path(self, path: str) -> Path:
        """Resolve a workspace destination path without requiring it to exist."""
        return self._path(path)

    def path_for(self, path: str) -> Path:
        target = self._path(path)
        if not target.exists():
            raise WorkspaceFileError(f"path not found: {path}")
        return target
