"""Receive and verify a body before committing its unique staged entry."""

import hashlib
from contextlib import AbstractContextManager
from typing import Protocol

from project_runtime_client.files.domain.attachment import AttachmentExpectation
from project_runtime_client.files.domain.receipts import WorkspaceIngestReceipt


class AttachmentBody(Protocol):
    @property
    def declared_size(self) -> int | None: ...
    def read(self) -> bytes: ...


class AttachmentSink(Protocol):
    def write(self, data: bytes) -> None: ...
    def flush(self) -> None: ...


class AttachmentTarget(Protocol):
    def writing(self) -> AbstractContextManager[AttachmentSink]: ...
    def commit(self) -> None: ...
    def receipt(self, digest: str) -> WorkspaceIngestReceipt: ...


class AttachmentStorage(Protocol):
    def target(
        self, destination: str, overwrite: bool
    ) -> AbstractContextManager[AttachmentTarget]: ...


class AttachmentTransport(Protocol):
    def open(self, url: str) -> AbstractContextManager[AttachmentBody]: ...


class IngestAttachment:
    def __init__(self, storage: AttachmentStorage, transport: AttachmentTransport) -> None:
        self._storage, self._transport = storage, transport

    def execute(
        self, url: str, destination: str, overwrite: bool, expected: AttachmentExpectation
    ) -> WorkspaceIngestReceipt:
        digest, total = hashlib.sha256(), 0
        with self._storage.target(destination, overwrite) as target:
            with self._transport.open(url) as body:
                declared = body.declared_size
                expected.require_declared(declared)
                with target.writing() as sink:
                    while chunk := body.read():
                        total += len(chunk)
                        expected.require_progress(total)
                        digest.update(chunk)
                        sink.write(chunk)
                    sink.flush()
            actual = digest.hexdigest()
            expected.require_complete(declared, total, actual)
            target.commit()
            return target.receipt(actual)
