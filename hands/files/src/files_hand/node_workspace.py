"""Original Files workspace API over pinned descriptors, never raw host paths."""
from __future__ import annotations

import base64
import hashlib
import os
import stat
import time
import unicodedata
from contextlib import contextmanager, suppress
from contextvars import ContextVar
from uuid import uuid4

from modules.files.project_workspace import _checked_entry, _components, _rename_no_replace
from modules.project_runtime.workspace_roots import ProjectFileError, _open_beneath

from ._project_files import FLAGS, ProjectFiles


MAX_BYTES = 256 * 1024 * 1024
MAX_ENTRIES = 10_000
_deadline = ContextVar("files_node_deadline", default=0.0)


class NodeWorkspace(ProjectFiles):
    @contextmanager
    def authority(self, expires_at):
        token = _deadline.set(expires_at)
        try:
            self.check()
            yield
            self.check()
        finally:
            _deadline.reset(token)

    @staticmethod
    def check():
        if time.time() >= _deadline.get():
            raise ValueError("Files execution authority expired")

    def components(self, path, *, root_allowed=False):
        self.check()
        if not isinstance(path, str) or not unicodedata.is_normalized("NFC", path):
            raise ValueError("Canonical relative path required")
        parts = _components(path, root_allowed=root_allowed)
        if any(part.startswith(".briareus-stage-") for part in parts):
            raise ValueError("Private Files staging name is reserved")
        return parts

    def checked(self, info):
        self.check()
        _checked_entry(info, device=self.root_info.st_dev)

    @contextmanager
    def parent(self, path, *, create=False):
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
    def entry(path, info):
        result = ProjectFiles.entry(path, info)
        result["modified_at_ns"] = info.st_mtime_ns
        return result

    def status(self):
        self.check()
        usage = os.fstatvfs(self.root)
        return {"root": "/", "free_bytes": usage.f_bavail * usage.f_frsize,
                "used_bytes": (usage.f_blocks - usage.f_bfree) * usage.f_frsize,
                "total_bytes": usage.f_blocks * usage.f_frsize}

    def info(self, path):
        self.components(path)
        with self.opened(path) as (_, info):
            return self.entry(path, info)

    def list(self, path="", *, offset=0, limit=200):
        self.components(path, root_allowed=True)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Bounded directory page required")
        result = []
        with self.opened(path, directory=True) as (fd, _):
            with os.scandir(fd) as entries:
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
        result.sort(key=lambda item: (item["type"] != "directory", item["name"].casefold()))
        selected = result[offset:offset + limit]
        return {"path": path or "/", "entries": selected, "count": len(selected), "total": len(result),
                "offset": offset, "limit": limit, "truncated": offset + len(selected) < len(result)}

    def read(self, path, *, offset=0, length=1024 * 1024):
        self.components(path)
        if (type(offset) is not int or offset < 0 or type(length) is not int
            or not 1 <= length <= 16 * 1024 * 1024):
            raise ValueError("Bounded file read required")
        with self.opened(path) as (fd, before):
            if not stat.S_ISREG(before.st_mode) or before.st_size > MAX_BYTES or offset > before.st_size:
                raise ValueError("Bounded regular file required")
            self.check()
            # A page is intentionally smaller than the transport's response
            # budget; original bytes_read/next_offset/eof describe the page.
            data = os.pread(fd, min(length, 262_144), offset)
            after = os.fstat(fd)
            self.check()
            if self.signature(before) != self.signature(after):
                raise ValueError("File changed during read")
            return {"path": path, "offset": offset, "bytes_read": len(data), "next_offset": offset + len(data),
                    "size_bytes": before.st_size, "eof": offset + len(data) >= before.st_size,
                    "data_base64": base64.b64encode(data).decode("ascii")}

    def sha256(self, path):
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
    def signature(info):
        return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)

    def existing(self, parent, name):
        try:
            info = os.stat(name, dir_fd=parent, follow_symlinks=False)
        except FileNotFoundError:
            return None
        self.checked(info)
        return info

    def commit(self, parent, temporary, name, *, overwrite):
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
    def staged(self, parent):
        name = ".briareus-stage-" + uuid4().hex
        fd = os.open(name, os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=parent)
        try:
            yield name, fd
        finally:
            os.close(fd)
            with suppress(FileNotFoundError):
                os.unlink(name, dir_fd=parent)

    def write_bytes(self, fd, data):
        view = memoryview(data)
        while view:
            self.check()
            written = os.write(fd, view[:1024 * 1024])
            if written <= 0:
                raise ValueError("File write did not progress")
            view = view[written:]

    def write_text(self, path, content, *, overwrite=True, create_parents=True):
        data = content.encode("utf-8")
        if len(data) > MAX_BYTES:
            raise ValueError("Text exceeds file budget")
        with self.parent(path, create=create_parents) as (parent, name), self.staged(parent) as (temporary, fd):
            self.write_bytes(fd, data)
            os.fsync(fd)
            self.commit(parent, temporary, name, overwrite=overwrite)
        return self.info(path)

    def write_chunk(self, path, data_base64, *, offset=0, truncate=False, create_parents=True, max_file_bytes=MAX_BYTES):
        data = base64.b64decode(data_base64, validate=True)
        if type(offset) is not int or offset < 0 or truncate and offset != 0:
            raise ValueError("Invalid chunk offset")
        if offset + len(data) > min(max_file_bytes, MAX_BYTES):
            raise ValueError("File exceeds configured size limit")
        with self.parent(path, create=create_parents) as (parent, name), self.staged(parent) as (temporary, fd):
            before = self.existing(parent, name)
            if before is not None and not stat.S_ISREG(before.st_mode):
                raise ValueError("Regular file required")
            if not truncate:
                if offset != (before.st_size if before is not None else 0):
                    raise ValueError("Chunk offset does not match current file size")
                if before is not None:
                    old = _open_beneath(parent, name, FLAGS)
                    try:
                        if self.signature(before) != self.signature(os.fstat(old)):
                            raise ValueError("File changed before append")
                        position = 0
                        while position < offset:
                            self.check()
                            chunk = os.pread(old, min(1024 * 1024, offset - position), position)
                            if not chunk:
                                raise ValueError("File changed during append")
                            self.write_bytes(fd, chunk)
                            position += len(chunk)
                        if self.signature(before) != self.signature(os.fstat(old)):
                            raise ValueError("File changed during append")
                    finally:
                        os.close(old)
            self.write_bytes(fd, data)
            os.fsync(fd)
            current = self.existing(parent, name)
            if before is not None and (current is None or self.signature(before) != self.signature(current)):
                raise ValueError("File changed before chunk commit")
            self.commit(parent, temporary, name, overwrite=before is not None)
        return {"path": path, "bytes_written": len(data), "next_offset": offset + len(data),
                "size_bytes": offset + len(data)}

    def mkdir(self, path, *, parents=True):
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

    def _count(self, budget):
        self.check()
        budget[0] += 1
        if budget[0] > MAX_ENTRIES:
            raise ValueError("Recursive Files operation exceeds entry budget")

    def _remove(self, parent, name, *, recursive, budget, depth=0):
        self._count(budget)
        if depth > 64:
            raise ValueError("Recursive Files depth exceeded")
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
                            self._remove(child, item.name, recursive=True, budget=budget, depth=depth + 1)
                self.check()
                os.rmdir(name, dir_fd=parent)
            finally:
                os.close(child)
        else:
            self.check()
            os.unlink(name, dir_fd=parent)
        os.fsync(parent)
        return True

    def delete(self, path, *, recursive=False):
        with self.parent(path) as (parent, name):
            deleted = self._remove(parent, name, recursive=recursive, budget=[0])
        return {"path": path, "deleted": True} if deleted else {"path": path, "already_absent": True}

    def _copy(self, source_parent, source_name, target_parent, target_name, budget, depth=0):
        self._count(budget)
        if depth > 64:
            raise ValueError("Recursive Files depth exceeded")
        source = _open_beneath(source_parent, source_name, FLAGS)
        try:
            before = os.fstat(source)
            self.checked(before)
            if stat.S_ISDIR(before.st_mode):
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
            else:
                if before.st_size > MAX_BYTES:
                    raise ValueError("Copy exceeds configured file limit")
                target = os.open(target_name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                                 0o600, dir_fd=target_parent)
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
        finally:
            os.close(source)

    def copy(self, source, destination, *, overwrite=False):
        self.components(source)
        self.components(destination)
        if destination == source or destination.startswith(source + "/"):
            raise ValueError("Destination cannot be inside source")
        with self.parent(source) as (source_parent, source_name), self.parent(destination, create=True) as (target_parent, target_name):
            if self.existing(target_parent, target_name) is not None and not overwrite:
                raise ValueError("Destination exists")
            temporary = ".briareus-stage-" + uuid4().hex
            try:
                self._copy(source_parent, source_name, target_parent, temporary, [0])
                if overwrite and self.existing(target_parent, target_name) is not None:
                    self._remove(target_parent, target_name, recursive=True, budget=[0])
                self.commit(target_parent, temporary, target_name, overwrite=False)
            finally:
                # Cleanup only the unique staging name; never follow a symlink
                # or continue a user mutation after its authority expired.
                if time.time() < _deadline.get():
                    with suppress(FileNotFoundError):
                        self._remove(target_parent, temporary, recursive=True, budget=[0])
        return self.info(destination)

    def move(self, source, destination, *, overwrite=False):
        self.components(source)
        self.components(destination)
        if destination == source or destination.startswith(source + "/"):
            raise ValueError("Destination cannot be inside source")
        with self.parent(source) as (source_parent, source_name), self.parent(destination, create=True) as (target_parent, target_name):
            if self.existing(source_parent, source_name) is None:
                raise ValueError("Move source not found")
            if overwrite and self.existing(target_parent, target_name) is not None:
                self._remove(target_parent, target_name, recursive=True, budget=[0])
            self.check()
            _rename_no_replace(source_parent, source_name, target_parent, target_name)
            os.fsync(source_parent)
            os.fsync(target_parent)
        return self.info(destination)

    def ingest(self, *, file, destination, expected_size=None, expected_sha256="", overwrite=False, **_):
        from modules.files._attachment_transport import open_public_attachment, validate_public_attachment_url
        from modules.files.workspace_ingress import _validate_sha256
        self.check()
        validate_public_attachment_url(file.download_url)
        expected_digest = _validate_sha256(expected_sha256)
        if expected_size is not None and (type(expected_size) is not int or not 0 <= expected_size <= MAX_BYTES):
            raise ValueError("Invalid expected attachment size")
        digest, total = hashlib.sha256(), 0
        with self.parent(destination, create=True) as (parent, name), self.staged(parent) as (temporary, fd):
            if self.existing(parent, name) is not None and not overwrite:
                raise ValueError("Attachment destination exists")
            with open_public_attachment(file.download_url, deadline=_deadline.get()) as response:
                lengths = response.headers.get_all("Content-Length", [])
                if len(lengths) > 1:
                    raise ValueError("Conflicting attachment length")
                declared = int(lengths[0]) if lengths else None
                if declared is not None and (not 0 <= declared <= MAX_BYTES
                    or expected_size is not None and declared != expected_size):
                    raise ValueError("Attachment length exceeds expected bounds")
                while True:
                    self.check()
                    data = response.read(1024 * 1024)
                    self.check()
                    if not data:
                        break
                    total += len(data)
                    if total > MAX_BYTES:
                        raise ValueError("Attachment size limit exceeded")
                    digest.update(data)
                    self.write_bytes(fd, data)
            if ((declared is not None and total != declared) or (expected_size is not None and total != expected_size)
                or expected_digest and digest.hexdigest() != expected_digest):
                raise ValueError("Attachment size or digest mismatch")
            os.fsync(fd)
            self.commit(parent, temporary, name, overwrite=overwrite)
        result = self.info(destination)
        result.update({"sha256": digest.hexdigest(), "completed": True, "transport": "client-file"})
        return result
