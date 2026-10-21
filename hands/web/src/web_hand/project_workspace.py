"""Shared Web transfers through confined descriptors and private staging.

Chromium/Playwright never receives a mutable shared-workspace pathname. Browser
profiles remain in their separate private storage volume.
"""
from contextlib import contextmanager, suppress
import ctypes
import os
from pathlib import Path
import shutil
import stat
import tempfile
import unicodedata

from modules.project_runtime.workspace_roots import _open_beneath
from modules.workspace_compat.legacy_store import WorkspaceFileStore, WorkspaceFileError

MAX_BYTES = 256 * 1024**2
FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK


class ProjectBrowserWorkspace(WorkspaceFileStore):
    def __init__(self, project_root, private_staging, *, read_only=False):
        super().__init__(private_staging)
        self.project_root = Path(project_root)
        self.read_only = read_only
        self.ensure()
        fd = self._root()
        os.close(fd)

    def _checked(self, info, *, directory=False, device=None):
        if (not (stat.S_ISDIR(info.st_mode) if directory else stat.S_ISREG(info.st_mode))
            or info.st_uid != 1000 or info.st_gid != 1000 or info.st_mode & 0o022
            or not directory and info.st_nlink != 1 or device is not None and info.st_dev != device):
            raise WorkspaceFileError("Unsafe shared workspace entry")

    def _root(self):
        fd = os.open(self.project_root, FLAGS | os.O_DIRECTORY)
        try:
            info = os.fstat(fd)
            self._checked(info, directory=True)
            if stat.S_IMODE(info.st_mode) != 0o700:
                raise WorkspaceFileError("Private project workspace root required")
            return fd
        except BaseException:
            os.close(fd)
            raise

    @contextmanager
    def _parent(self, value, *, create=False):
        if (not isinstance(value,str) or not value or not unicodedata.is_normalized("NFC",value)
            or value.startswith("/") or "\\" in value or "\0" in value):
            raise WorkspaceFileError("Canonical relative workspace path required")
        parts = value.split("/")
        if any(part in {"", ".", ".."} or part.startswith(".briareus-") for part in parts):
            raise WorkspaceFileError("Canonical relative workspace path required")
        fd = self._root()
        device = os.fstat(fd).st_dev
        try:
            for part in parts[:-1]:
                if create:
                    with suppress(FileExistsError):
                        os.mkdir(part, 0o700, dir_fd=fd)
                child = _open_beneath(fd,part,FLAGS | os.O_DIRECTORY)
                try:
                    self._checked(os.fstat(child),directory=True,device=device)
                except BaseException:
                    os.close(child)
                    raise
                os.close(fd)
                fd = child
            yield fd,parts[-1],device
        finally:
            os.close(fd)

    @contextmanager
    def upload_source(self, value):
        with self._parent(value) as (parent,name,device):
            source = _open_beneath(parent,name,FLAGS)
            temporary = Path(tempfile.mkdtemp(prefix="upload-",dir=self.root))
            try:
                info = os.fstat(source)
                self._checked(info,device=device)
                if info.st_size > MAX_BYTES:
                    raise WorkspaceFileError("Browser transfer exceeds its bounded size")
                target = temporary / name
                total = 0
                with target.open("xb") as output:
                    os.chmod(target,0o600)
                    while block := os.read(source,1024**2):
                        total += len(block)
                        if total > MAX_BYTES:
                            raise WorkspaceFileError("Browser transfer exceeds its bounded size")
                        output.write(block)
                after = os.fstat(source)
                if (after.st_size,after.st_mtime_ns,after.st_ctime_ns) != (info.st_size,info.st_mtime_ns,info.st_ctime_ns):
                    raise WorkspaceFileError("Upload changed during staging")
                yield target
            finally:
                os.close(source)
                shutil.rmtree(temporary)

    @contextmanager
    def download_target(self, value, *, overwrite):
        if self.read_only:
            raise WorkspaceFileError("Shared project workspace is read-only")
        with self._parent(value,create=True) as (parent,name,device):
            self._destination(parent,name,device,overwrite)
            temporary = Path(tempfile.mkdtemp(prefix="download-",dir=self.root))
            target = temporary / name
            try:
                yield target
                source = os.open(target,FLAGS)
                staging = ".briareus-web-" + os.urandom(16).hex()
                output = None
                try:
                    info = os.fstat(source)
                    self._checked(info)
                    if info.st_size > MAX_BYTES:
                        raise WorkspaceFileError("Browser transfer exceeds its bounded size")
                    output = os.open(staging,os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,0o600,dir_fd=parent)
                    total = 0
                    while block := os.read(source,1024**2):
                        total += len(block)
                        if total > MAX_BYTES:
                            raise WorkspaceFileError("Browser transfer exceeds its bounded size")
                        view = memoryview(block)
                        while view:
                            written = os.write(output,view)
                            view = view[written:]
                    os.fsync(output)
                    self._destination(parent,name,device,overwrite)
                    if overwrite:
                        os.replace(staging,name,src_dir_fd=parent,dst_dir_fd=parent)
                    else:
                        rename = ctypes.CDLL(None,use_errno=True).renameat2
                        if rename(parent,staging.encode(),parent,name.encode(),1) != 0:
                            code = ctypes.get_errno()
                            raise OSError(code,os.strerror(code))
                    os.fsync(parent)
                finally:
                    os.close(source)
                    if output is not None:
                        os.close(output)
                    with suppress(FileNotFoundError):
                        os.unlink(staging,dir_fd=parent)
            finally:
                shutil.rmtree(temporary)

    def _destination(self,parent,name,device,overwrite):
        try:
            info = os.stat(name,dir_fd=parent,follow_symlinks=False)
        except FileNotFoundError:
            return
        self._checked(info,device=device)
        if not overwrite:
            raise WorkspaceFileError("Destination already exists")

    def info(self,value):
        with self._parent(value) as (parent,name,device):
            descriptor = _open_beneath(parent,name,FLAGS)
            try:
                info = os.fstat(descriptor)
                self._checked(info,device=device)
                return {"path":value,"name":name,"type":"file","size_bytes":info.st_size,"modified_at_ns":info.st_mtime_ns}
            finally:
                os.close(descriptor)
