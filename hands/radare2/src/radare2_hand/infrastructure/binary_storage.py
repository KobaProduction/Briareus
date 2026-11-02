"""Descriptor-confined binary storage and durable bytes-before-manifest publication."""

import os
import stat
from pathlib import Path
from uuid import UUID

from pydantic import TypeAdapter

from radare2_hand.application.imports import BinaryReceipt
from radare2_hand.application.inspection import NativeBinary
from radare2_hand.domain.binaries import MAX_BINARY, BinaryManifest, identifier, require_identifier


def read_private(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        facts = os.fstat(descriptor)
        if not stat.S_ISREG(facts.st_mode) or facts.st_size > maximum or facts.st_nlink != 1:
            raise ValueError("Private bounded regular file required")
        with os.fdopen(descriptor, "rb", closefd=False) as stream:
            value = stream.read(maximum + 1)
        if len(value) > maximum:
            raise ValueError("Stored analysis data exceeds limit")
        return value
    finally:
        os.close(descriptor)


def write_private(path: Path, value: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


_MANIFEST: TypeAdapter[BinaryManifest] = TypeAdapter(BinaryManifest)


def parse_manifest(raw: bytes) -> BinaryManifest:
    return _MANIFEST.validate_json(raw, strict=True)


class BinaryFiles:
    def __init__(self, root: Path) -> None:
        if not root.is_dir() or root.is_symlink():
            raise ValueError("An independently provisioned private analysis volume is required")
        self.root = root
        for name in ("uploads", "binaries"):
            target = root / name
            target.mkdir(mode=0o700, exist_ok=True)
            if target.is_symlink() or not target.is_dir():
                raise ValueError("Private analysis directories required")
            os.chmod(target, 0o700)

    def path(self, kind: str, handle: UUID, suffix: str = "") -> Path:
        return self.root / kind / (str(require_identifier(handle)) + suffix)

    def manifests(self) -> tuple[BinaryManifest, ...]:
        return tuple(
            parse_manifest(read_private(path, 4096)) for path in self.root.glob("*/*.json")
        )

    def manifest(self, kind: str, handle: UUID) -> BinaryManifest:
        return parse_manifest(read_private(self.path(kind, handle, ".json"), 4096))

    def create(self, upload: UUID, metadata: BinaryManifest) -> None:
        write_private(self.path("uploads", upload), b"")
        try:
            write_private(self.path("uploads", upload, ".json"), _MANIFEST.dump_json(metadata))
        except BaseException:
            self.path("uploads", upload).unlink(missing_ok=True)
            raise

    def append(self, upload: UUID, offset: int, data: bytes) -> None:
        descriptor = os.open(
            self.path("uploads", upload), os.O_WRONLY | getattr(os, "O_NOFOLLOW", 0)
        )
        with os.fdopen(descriptor, "r+b") as stream:
            facts = os.fstat(stream.fileno())
            if not stat.S_ISREG(facts.st_mode) or facts.st_nlink != 1 or facts.st_size != offset:
                raise ValueError("Upload offset does not match committed bytes")
            stream.seek(offset)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())

    def published(self, binary: UUID) -> bool:
        return self.path("binaries", binary, ".json").exists()

    def read_commit_bytes(self, upload: UUID) -> bytes:
        source = self.path("uploads", upload)
        return read_private(
            source if source.exists() else self.path("binaries", upload), MAX_BINARY
        )

    def publish(self, upload: UUID) -> None:
        source, target = self.path("uploads", upload), self.path("binaries", upload)
        if source.exists():
            if target.exists():
                raise ValueError("Conflicting analysis import state")
            source.rename(target)
        self.path("uploads", upload, ".json").rename(self.path("binaries", upload, ".json"))
        if os.name == "posix":
            sync_directory(source.parent)
            sync_directory(target.parent)

    def remove(self, kind: str, handle: UUID) -> None:
        self.path(kind, handle).unlink()
        self.path(kind, handle, ".json").unlink()

    def listing(self) -> tuple[BinaryReceipt, ...]:
        return tuple(
            BinaryReceipt.from_manifest(
                identifier(path.stem), self.manifest("binaries", identifier(path.stem))
            )
            for path in sorted(self.root.glob("binaries/*.json"))
        )

    def load(self, binary_id: UUID) -> NativeBinary:
        path = self.path("binaries", binary_id)
        return NativeBinary(
            str(path), self.manifest("binaries", binary_id), read_private(path, MAX_BINARY)
        )


def sync_directory(directory: Path) -> None:
    descriptor = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
