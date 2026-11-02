"""Failed attachment identity never reaches atomic commit."""

import hashlib
import unittest
from collections.abc import Iterator
from contextlib import contextmanager

from files_hand.application.ingest_attachment import (
    AttachmentBody,
    AttachmentStage,
    IngestAttachment,
)
from files_hand.domain.attachment import AttachmentExpectation


class Body:
    def __init__(self, declared: int | None) -> None:
        self.declared_size = declared
        self.chunks = iter((b"payload", b""))

    def read(self) -> bytes:
        return next(self.chunks)


class Storage:
    def __init__(self, declared: int | None = 7) -> None:
        self.body = Body(declared)
        self.written = bytearray()
        self.committed = False
        self.closed = False

    @contextmanager
    def stage(self, destination: str, overwrite: bool) -> Iterator[AttachmentStage]:
        self.destination, self.overwrite = destination, overwrite
        try:
            yield self
        finally:
            self.closed = True

    @contextmanager
    def open(self, url: str) -> Iterator[AttachmentBody]:
        self.url = url
        yield self.body

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    def commit(self) -> None:
        self.committed = True


class IngestUseCaseTests(unittest.TestCase):
    def test_verified_body_commits_and_returns_digest(self) -> None:
        storage = Storage()
        digest = hashlib.sha256(b"payload").hexdigest()
        result = IngestAttachment(storage).execute(
            "https://public.test/file", "target", False, AttachmentExpectation(7, digest)
        )
        self.assertEqual((result.sha256, result.size_bytes), (digest, 7))
        self.assertEqual(storage.written, b"payload")
        self.assertEqual((storage.destination, storage.overwrite), ("target", False))
        self.assertEqual(storage.url, "https://public.test/file")
        self.assertTrue(storage.committed)
        self.assertTrue(storage.closed)

    def test_mismatch_closes_stage_without_commit(self) -> None:
        for declared, expected in (
            (8, AttachmentExpectation(None, "")),
            (7, AttachmentExpectation(8, "")),
            (None, AttachmentExpectation(None, "0" * 64)),
        ):
            with self.subTest(declared=declared, expected=expected):
                storage = Storage(declared)
                with self.assertRaisesRegex(ValueError, "Attachment"):
                    IngestAttachment(storage).execute(
                        "https://public.test/file", "target", False, expected
                    )
                self.assertFalse(storage.committed)
                self.assertTrue(storage.closed)

    def test_invalid_expectations_are_rejected(self) -> None:
        for size in (-1, True, 2**63):
            with self.assertRaises(ValueError):
                AttachmentExpectation(size, "")
        with self.assertRaises(ValueError):
            AttachmentExpectation(None, "G" * 64)
