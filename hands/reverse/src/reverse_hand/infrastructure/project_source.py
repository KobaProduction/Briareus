"""Descriptor-relative read-only project snapshot; no host-selected paths or symlink traversal."""

import hashlib
import os
import stat
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import NamedTuple

from reverse_hand.domain.project_source import (
    ProjectSourcePath,
    SourceDescriptor,
    SourceFingerprint,
    require_copied_size,
)


class SourceSnapshot(NamedTuple):
    path: Path
    size_bytes: int
    sha256: str


def descriptor_facts(descriptor: int) -> SourceDescriptor:
    info = os.fstat(descriptor)
    return SourceDescriptor(
        info.st_uid,
        info.st_gid,
        info.st_mode,
        info.st_dev,
        stat.S_ISREG(info.st_mode),
        info.st_nlink,
        SourceFingerprint(info.st_size, info.st_mtime_ns, info.st_ctime_ns),
    )


def open_source(root: Path, source: ProjectSourcePath) -> int:
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK
    descriptor = os.open(root, flags | os.O_DIRECTORY)
    try:
        device = os.fstat(descriptor).st_dev
        for index, part in enumerate(source.parts):
            child = os.open(
                part,
                flags | (os.O_DIRECTORY if index < len(source.parts) - 1 else 0),
                dir_fd=descriptor,
            )
            os.close(descriptor)
            descriptor = child
            descriptor_facts(descriptor).require_owner(device)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def copy_snapshot(descriptor: int, target: Path) -> SourceSnapshot:
    digest = hashlib.sha256()
    total = 0
    with target.open("xb") as output:
        while block := os.read(descriptor, 1024**2):
            total += len(block)
            require_copied_size(total)
            digest.update(block)
            output.write(block)
    return SourceSnapshot(target, total, digest.hexdigest())


@contextmanager
def source_snapshot(
    relative: str,
    root: Path = Path("/workspace/project"),
    staging: Path = Path("/project-data/ghidra/cache"),
) -> Iterator[SourceSnapshot]:
    source = ProjectSourcePath(relative)
    descriptor = open_source(root, source)
    try:
        original = descriptor_facts(descriptor)
        original.require_artifact()
        with tempfile.TemporaryDirectory(prefix="transfer-", dir=staging) as temporary:
            receipt = copy_snapshot(descriptor, Path(temporary) / source.parts[-1])
            original.fingerprint.require_unchanged(descriptor_facts(descriptor).fingerprint)
            yield receipt
    finally:
        os.close(descriptor)
