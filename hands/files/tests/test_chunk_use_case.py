"""Atomic chunk workflow rules do not require a filesystem or MCP server."""

import json
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace

from files_hand.application.write_chunk import ChunkStage, ChunkWrite, ChunkWriteReceipt, WriteChunk
from files_hand.domain.chunk_write import FileSnapshot
from files_hand.presentation.results import file_result


@dataclass
class StagingFixture:
    before: FileSnapshot | None
    steps: list[str] = field(default_factory=list)
    reject_copy: bool = False

    def existing(self) -> FileSnapshot | None:
        return self.before

    def copy_prefix(self, before: FileSnapshot, length: int) -> None:
        if before != self.before or length != before.size_bytes:
            raise AssertionError("Only the observed prefix can be copied")
        self.steps.append("copy")
        if self.reject_copy:
            raise ValueError("File changed during append")

    def write(self, _data: bytes) -> None:
        self.steps.append("write")

    def publish(self, before: FileSnapshot | None) -> None:
        if before != self.before:
            raise AssertionError("The commit must use the same file observation")
        self.steps.append("commit")

    @contextmanager
    def stage(self, _path: str, *, create_parents: bool) -> Iterator[ChunkStage]:
        self.steps.append("create-parents" if create_parents else "existing-parent")
        try:
            yield self
        finally:
            self.steps.append("cleanup")


class ChunkUseCaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.before = FileSnapshot((1, 2, 4, 5, 6), 4, True)
        self.storage = StagingFixture(self.before)
        self.use_case = WriteChunk(self.storage)
        self.command = ChunkWrite("file", b"new", 4, False, True, 100)

    def test_append_preserves_observation_until_atomic_publish(self) -> None:
        self.assertEqual(self.use_case.execute(self.command), ChunkWriteReceipt("file", 3, 7, 7))
        self.assertEqual(
            self.storage.steps, ["create-parents", "copy", "write", "commit", "cleanup"]
        )

    def test_truncate_does_not_read_existing_prefix(self) -> None:
        self.use_case.execute(replace(self.command, offset=0, truncate=True))
        self.assertNotIn("copy", self.storage.steps)
        self.assertIn("commit", self.storage.steps)

    def test_failed_copy_never_publishes_and_always_cleans_stage(self) -> None:
        self.storage.reject_copy = True
        with self.assertRaises(ValueError):
            self.use_case.execute(self.command)
        self.assertEqual(self.storage.steps, ["create-parents", "copy", "cleanup"])

    def test_wrong_offset_or_special_file_never_writes(self) -> None:
        for before in (
            None,
            replace(self.before, size_bytes=5),
            replace(self.before, regular=False),
        ):
            with self.subTest(before=before):
                storage = StagingFixture(before)
                with self.assertRaises(ValueError):
                    WriteChunk(storage).execute(self.command)
                self.assertEqual(storage.steps, ["create-parents", "cleanup"])

    def test_limit_and_offset_validation_precedes_storage_effects(self) -> None:
        for offset, truncate, limit in ((-1, False, 100), (2, True, 100), (4, False, 6)):
            with self.subTest(offset=offset, truncate=truncate), self.assertRaises(ValueError):
                replace(self.command, offset=offset, truncate=truncate, max_file_bytes=limit)
        self.assertEqual(self.storage.steps, [])

    def test_mcp_adapter_preserves_existing_receipt_wire_shape(self) -> None:
        receipt = self.use_case.execute(self.command)
        reply = file_result(receipt)
        self.assertEqual(
            reply.structured_content,
            {
                "path": "file",
                "bytes_written": 3,
                "next_offset": 7,
                "size_bytes": 7,
            },
        )
        first = reply.content[0]
        if first.type != "text":
            self.fail("Text receipt required")
        self.assertEqual(json.loads(first.text), reply.structured_content)
        self.assertFalse(reply.is_error)

    def test_nonfinite_result_still_fails_at_the_mcp_boundary(self) -> None:
        with self.assertRaises(ValueError):
            file_result({"size_bytes": float("nan")})
