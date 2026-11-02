"""Binary import use cases preserve the original UUID across crash recovery and publication."""

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

from radare2_hand.domain.binaries import (
    MAX_BINARY,
    MAX_CHUNK,
    BinaryManifest,
    bounded_int,
    decode_chunk,
    require_capacity,
    require_chunk,
    require_identifier,
)


@dataclass(frozen=True, slots=True)
class PendingUpload:
    upload_id: UUID
    size: int
    chunk_bytes: int = MAX_CHUNK
    offset: int = 0


@dataclass(frozen=True, slots=True)
class ChunkReceipt:
    upload_id: UUID
    offset: int
    size: int


@dataclass(frozen=True, slots=True)
class BinaryReceipt:
    binary_id: UUID
    name: str
    sha256: str
    size: int
    created_at: int

    @classmethod
    def from_manifest(cls, binary: UUID, metadata: BinaryManifest) -> "BinaryReceipt":
        return cls(binary, metadata.name, metadata.sha256, metadata.size, metadata.created_at)


@dataclass(frozen=True, slots=True)
class BinaryListing:
    binaries: tuple[BinaryReceipt, ...]


@dataclass(frozen=True, slots=True)
class UploadAborted:
    upload_id: UUID
    state: Literal["aborted"] = "aborted"


@dataclass(frozen=True, slots=True)
class BinaryDeleted:
    binary_id: UUID
    state: Literal["deleted"] = "deleted"


class BinaryStorage(Protocol):
    def manifests(self) -> tuple[BinaryManifest, ...]: ...
    def create(self, upload: UUID, metadata: BinaryManifest) -> None: ...
    def manifest(self, kind: str, handle: UUID) -> BinaryManifest: ...
    def append(self, upload: UUID, offset: int, data: bytes) -> None: ...
    def published(self, binary: UUID) -> bool: ...
    def read_commit_bytes(self, upload: UUID) -> bytes: ...
    def publish(self, upload: UUID) -> None: ...
    def remove(self, kind: str, handle: UUID) -> None: ...
    def listing(self) -> tuple[BinaryReceipt, ...]: ...


class BinaryImports:
    def __init__(
        self,
        storage: BinaryStorage,
        lock: asyncio.Lock,
        new_uuid: Callable[[], UUID],
        now: Callable[[], int],
    ) -> None:
        self.storage = storage
        self.lock = lock
        self.new_uuid = new_uuid
        self.now = now

    async def start(self, name: str, sha256: str, size: int) -> PendingUpload:
        metadata = BinaryManifest(name, sha256, size, self.now())
        metadata.require_upload()
        async with self.lock:
            require_capacity(self.storage.manifests(), size)
            upload = self.new_uuid()
            self.storage.create(upload, metadata)
            return PendingUpload(upload, size)

    async def chunk(self, upload_id: UUID, offset: int, content_base64: str) -> ChunkReceipt:
        data = decode_chunk(content_base64)
        bounded_int(offset, 0, MAX_BINARY)
        async with self.lock:
            metadata = self.storage.manifest("uploads", upload_id)
            require_chunk(metadata, offset=offset, length=len(data))
            self.storage.append(upload_id, offset, data)
            return ChunkReceipt(upload_id, offset + len(data), metadata.size)

    async def finish(self, upload_id: UUID) -> BinaryReceipt:
        async with self.lock:
            binary = require_identifier(upload_id)
            if self.storage.published(binary):
                return BinaryReceipt.from_manifest(
                    binary, self.storage.manifest("binaries", binary)
                )
            metadata = self.storage.manifest("uploads", upload_id)
            metadata.require_integrity(self.storage.read_commit_bytes(upload_id))
            self.storage.publish(upload_id)
            return BinaryReceipt.from_manifest(binary, metadata)

    async def abort(self, upload_id: UUID) -> UploadAborted:
        async with self.lock:
            self.storage.manifest("uploads", upload_id)
            self.storage.remove("uploads", upload_id)
            return UploadAborted(upload_id)

    async def listing(self) -> BinaryListing:
        async with self.lock:
            return BinaryListing(self.storage.listing())

    async def delete(self, binary_id: UUID) -> BinaryDeleted:
        async with self.lock:
            self.storage.manifest("binaries", binary_id)
            self.storage.remove("binaries", binary_id)
            return BinaryDeleted(binary_id)


type ImportResult = (
    PendingUpload | ChunkReceipt | BinaryReceipt | UploadAborted | BinaryListing | BinaryDeleted
)
