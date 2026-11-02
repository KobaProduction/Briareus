"""Stream and commit an attachment only after its identity is verified."""

import hashlib
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from files_hand.domain.attachment import AttachmentExpectation

from ._storage_binding import _StorageBinding


class AttachmentBody(Protocol):
    @property
    def declared_size(self) -> int | None: ...

    def read(self) -> bytes: ...


class AttachmentStage(Protocol):
    def write(self, data: bytes) -> None: ...
    def commit(self) -> None: ...


class AttachmentStorage(Protocol):
    def stage(
        self, destination: str, overwrite: bool
    ) -> AbstractContextManager[AttachmentStage]: ...
    def open(self, url: str) -> AbstractContextManager[AttachmentBody]: ...


@dataclass(frozen=True)
class AttachmentReceipt:
    sha256: str
    size_bytes: int


class IngestAttachment(_StorageBinding[AttachmentStorage]):
    def execute(
        self, url: str, destination: str, overwrite: bool, expected: AttachmentExpectation
    ) -> AttachmentReceipt:
        digest, total = hashlib.sha256(), 0
        with self._storage.stage(destination, overwrite) as stage:
            with self._storage.open(url) as body:
                declared = body.declared_size
                expected.require_declared(declared)
                while data := body.read():
                    total += len(data)
                    expected.require_progress(total)
                    digest.update(data)
                    stage.write(data)
            actual = digest.hexdigest()
            expected.require_complete(declared, total, actual)
            stage.commit()
        return AttachmentReceipt(actual, total)
