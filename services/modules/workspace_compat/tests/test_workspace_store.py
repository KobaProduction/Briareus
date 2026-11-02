"""Typed legacy receipts retain workspace bounds and filesystem behavior."""

import base64
import io
import tempfile
import unittest
from dataclasses import fields
from pathlib import Path

from modules.workspace_compat.domain.receipts import (
    WorkspaceAbsent,
    WorkspaceDeleted,
    WorkspaceDirectoryEntry,
    WorkspaceFileEntry,
)
from modules.workspace_compat.legacy_store import WorkspaceFileError, WorkspaceFileStore


class WorkspaceStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "workspace"
        self.store = WorkspaceFileStore(self.root)

    def test_directory_and_file_receipts_keep_distinct_exact_fields(self) -> None:
        directory = self.store.mkdir("directory")
        file = self.store.write_text("hello.txt", "hello")
        self.assertIsInstance(directory, WorkspaceDirectoryEntry)
        self.assertIsInstance(file, WorkspaceFileEntry)
        self.assertNotIn("mime_type", {field.name for field in fields(directory)})
        self.assertEqual(file.size_bytes, 5)
        self.assertEqual(file.path, "hello.txt")
        listing = self.store.list(limit=1)
        self.assertEqual(listing.entries, (directory,))
        self.assertEqual((listing.count, listing.total, listing.truncated), (1, 2, True))

    def test_append_validates_position_and_quota_before_changing_content(self) -> None:
        chunk = base64.b64encode(b"abc").decode("ascii")
        receipt = self.store.write_chunk("data.bin", chunk, max_file_bytes=6)
        self.assertEqual(
            (receipt.bytes_written, receipt.next_offset, receipt.size_bytes), (3, 3, 3)
        )
        for offset, quota in ((0, 6), (3, 5)):
            with self.subTest(offset=offset, quota=quota), self.assertRaises(WorkspaceFileError):
                self.store.write_chunk("data.bin", chunk, offset=offset, max_file_bytes=quota)
        self.assertEqual(self.store.path_for("data.bin").read_bytes(), b"abc")
        self.store.write_chunk("data.bin", chunk, offset=3, max_file_bytes=6)
        page = self.store.read("data.bin", offset=2, length=2)
        self.assertEqual(base64.b64decode(page.data_base64), b"ca")
        self.assertEqual(
            (page.offset, page.next_offset, page.size_bytes, page.eof), (2, 4, 6, False)
        )
        self.store.write_chunk("data.bin", "", truncate=True, max_file_bytes=6)
        self.assertEqual(self.store.info("data.bin").size_bytes, 0)

    def test_read_bounds_and_confined_paths_deny_without_outside_mutation(self) -> None:
        self.store.write_text("data.bin", "abc")
        for offset, length in ((-1, 2), (0, 0), (4, 2), (0, 16 * 1024 * 1024 + 1)):
            with self.subTest(offset=offset, length=length), self.assertRaises(WorkspaceFileError):
                self.store.read("data.bin", offset=offset, length=length)
        with self.assertRaises(WorkspaceFileError):
            self.store.write_text("../outside.txt", "escape")
        self.assertFalse((self.root.parent / "outside.txt").exists())
        with self.assertRaises(WorkspaceFileError):
            self.store.delete(".", recursive=True)
        self.assertEqual(self.store.path_for("data.bin").read_text(), "abc")

    def test_stream_commit_retains_existing_target_without_overwrite_and_cleans_staging(
        self,
    ) -> None:
        self.store.write_text("target.bin", "original")
        with self.assertRaises(WorkspaceFileError):
            self.store.put_stream(io.BytesIO(b"new"), "target.bin")
        self.assertEqual(self.store.path_for("target.bin").read_text(), "original")
        result = self.store.put_stream(io.BytesIO(b"new"), "target.bin", overwrite=True)
        self.assertEqual(result.size_bytes, 3)
        self.assertEqual(self.store.path_for("target.bin").read_bytes(), b"new")
        self.assertEqual(tuple(self.root.glob(".*.part")), ())

    def test_copy_move_and_delete_do_not_allow_workspace_root_or_recursive_self_copy(self) -> None:
        self.store.mkdir("directory")
        self.store.write_text("directory/a.txt", "content")
        with self.assertRaises(WorkspaceFileError):
            self.store.copy("directory", "directory/subdirectory")
        self.store.copy("directory/a.txt", "copy.txt")
        moved = self.store.move("copy.txt", "moved.txt")
        self.assertEqual(moved.path, "moved.txt")
        self.assertIsInstance(self.store.delete("moved.txt"), WorkspaceDeleted)
        self.assertIsInstance(self.store.delete("moved.txt"), WorkspaceAbsent)
