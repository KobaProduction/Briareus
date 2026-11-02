"""Real Linux descriptor I/O fixtures, independent of production identity."""

from __future__ import annotations

import base64
import hashlib
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from files_hand.node_workspace import NodeWorkspace

from modules.project_runtime.workspace_roots import ProjectFileError

DENIED = (ValueError, OSError, ProjectFileError)


class NodeWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name) / "project"
        self.root.mkdir(mode=0o700)
        self.workspace = NodeWorkspace(self.root)
        self.authority = self.workspace.authority(time.time() + 5)
        self.authority.__enter__()

    def tearDown(self):
        self.authority.__exit__(None, None, None)
        self.workspace.close()
        self.temporary.cleanup()

    def test_original_read_write_directory_copy_move_delete_workflow(self):
        workspace = self.workspace
        workspace.mkdir("nested/data")
        workspace.write_text("nested/data/file.txt", "original")
        workspace.write_chunk(
            "nested/data/file.txt", base64.b64encode(b" appended").decode(), offset=8
        )
        self.assertEqual(
            base64.b64decode(workspace.read("nested/data/file.txt").data_base64),
            b"original appended",
        )
        self.assertEqual(
            workspace.sha256("nested/data/file.txt"),
            hashlib.sha256(b"original appended").hexdigest(),
        )
        workspace.copy("nested", "copied")
        workspace.move("copied/data/file.txt", "moved/file.txt")
        self.assertEqual(workspace.info("moved/file.txt").size_bytes, 17)
        self.assertEqual(workspace.list("moved").total, 1)
        workspace.delete("copied", recursive=True)
        workspace.delete("moved/file.txt")
        self.assertTrue(workspace.delete("moved/file.txt").already_absent)
        self.assertEqual(workspace.list("moved").total, 0)
        self.assertNotIn(str(self.root), str(workspace.status()))

    def test_traversal_symlinks_and_special_files_never_escape_project(self):
        outside = Path(self.temporary.name) / "outside"
        outside.write_bytes(b"outside must survive")
        outside.chmod(0o600)
        (self.root / "escape").symlink_to(outside)
        for path in ("../outside", "/etc/passwd", "escape", "./file", "a/../file", "a\\file"):
            with self.subTest(path=path):
                for operation in (
                    lambda: self.workspace.read(path),
                    lambda: self.workspace.write_text(path, "bad"),
                    lambda: self.workspace.move(path, "moved"),
                    lambda: self.workspace.delete(path, recursive=True),
                ):
                    with self.assertRaises(DENIED):
                        operation()
        os.mkfifo(self.root / "fifo", 0o600)
        with self.assertRaises(DENIED):
            self.workspace.read("fifo")
        self.assertEqual(outside.read_bytes(), b"outside must survive")

    def test_hardlinked_files_are_neither_read_nor_overwritten(self):
        target = self.root / "one"
        target.write_bytes(b"must survive")
        target.chmod(0o600)
        os.link(target, self.root / "two")
        for operation in (
            lambda: self.workspace.read("one"),
            lambda: self.workspace.write_text("one", "bad"),
            lambda: self.workspace.copy("one", "copy"),
        ):
            with self.assertRaises(DENIED):
                operation()
        self.assertEqual(target.read_bytes(), b"must survive")

    def test_expired_authority_cannot_create_or_commit(self):
        with self.assertRaises(ValueError):
            with self.workspace.authority(time.time() - 1):
                self.workspace.write_text("never", "bad")
        self.assertFalse((self.root / "never").exists())
        original = self.workspace.commit

        def expire_before_commit(*args, **kwargs):
            with self.workspace.authority(time.time() - 1):
                original(*args, **kwargs)

        with patch.object(self.workspace, "commit", expire_before_commit):
            with self.assertRaises(ValueError):
                self.workspace.write_text("never", "bad")
        self.assertFalse((self.root / "never").exists())
        self.assertFalse(list(self.root.glob(".briareus-stage-*")))

    def test_swap_to_symlink_before_atomic_commit_cannot_write_outside(self):
        outside = Path(self.temporary.name) / "outside"
        outside.write_bytes(b"outside")
        outside.chmod(0o600)
        original = self.workspace.commit

        def swap(parent, temporary, name, **kwargs):
            os.symlink(outside, name, dir_fd=parent)
            return original(parent, temporary, name, **kwargs)

        with patch.object(self.workspace, "commit", swap):
            with self.assertRaises(DENIED):
                self.workspace.write_text("raced", "bad")
        self.assertEqual(outside.read_bytes(), b"outside")

    def test_read_detects_inode_change_and_pages_large_files(self):
        target = self.root / "large"
        target.write_bytes(b"x" * (1024 * 1024))
        target.chmod(0o600)
        page = self.workspace.read("large")
        self.assertEqual(page.bytes_read, 262_144)
        self.assertFalse(page.eof)
        original = os.pread

        def changing(*args):
            result = original(*args)
            with target.open("ab") as handle:
                handle.write(b"changed")
            return result

        with patch.object(os, "pread", changing):
            with self.assertRaises(ValueError):
                self.workspace.read("large")


if __name__ == "__main__":
    unittest.main()
