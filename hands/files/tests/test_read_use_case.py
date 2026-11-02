"""Stable page receipts cannot outlive a changed file snapshot."""

import unittest
from collections.abc import Iterator
from contextlib import contextmanager

from files_hand.application.read_file import FileReadSource, ReadFile
from files_hand.domain.chunk_write import FileSnapshot
from files_hand.domain.file_read import FileReadWindow


class Storage:
    def __init__(self, size: int = 1_000_000, *, changed: bool = False) -> None:
        self.before = FileSnapshot((1, 2, size, 4, 5), size, True)
        self.changed = changed
        self.calls: list[tuple[int, int]] = []
        self.closed = False
        self.path = ""

    @contextmanager
    def open(self, path: str) -> Iterator[FileReadSource]:
        self.path = path
        try:
            yield self
        finally:
            self.closed = True

    def read(self, offset: int, length: int) -> bytes:
        self.calls.append((offset, length))
        return b"x" * min(length, self.before.size_bytes - offset)

    def current(self) -> FileSnapshot:
        if self.changed:
            return FileSnapshot((1, 2, 1, 4, 6), 1, True)
        return self.before


class ReadUseCaseTests(unittest.TestCase):
    def test_paging_uses_transport_budget_and_preserves_cursor(self) -> None:
        storage = Storage()
        page = ReadFile(storage).execute("data", FileReadWindow(10, 1024 * 1024))
        self.assertEqual(storage.calls, [(10, 262_144)])
        self.assertEqual((page.path, page.offset, page.next_offset), ("data", 10, 262_154))
        self.assertFalse(page.eof)
        self.assertTrue(storage.closed)

    def test_eof_and_changed_snapshot(self) -> None:
        storage = Storage(2)
        page = ReadFile(storage).execute("data", FileReadWindow(2, 1))
        self.assertEqual(page.data, b"")
        self.assertTrue(page.eof)
        changed = Storage(changed=True)
        with self.assertRaisesRegex(ValueError, "File changed during read"):
            ReadFile(changed).execute("data", FileReadWindow())
        self.assertTrue(changed.closed)

    def test_invalid_ranges_and_nonregular_source_never_read(self) -> None:
        for offset, length in ((-1, 1), (True, 1), (0, 0), (0, 16 * 1024 * 1024 + 1)):
            with self.assertRaises(ValueError):
                FileReadWindow(offset, length)
        storage = Storage(2)
        with self.assertRaisesRegex(ValueError, "Bounded regular file required"):
            ReadFile(storage).execute("data", FileReadWindow(3, 1))
        storage.before = FileSnapshot((1, 2, 0, 4, 5), 0, False)
        with self.assertRaisesRegex(ValueError, "Bounded regular file required"):
            ReadFile(storage).execute("data", FileReadWindow())
        self.assertEqual(storage.calls, [])
