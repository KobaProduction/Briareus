"""Stale display cleanup must not follow worker-controlled filesystem links."""
import socket
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from web_hand.display_cleanup import clean_display


class DisplayCleanupTests(unittest.TestCase):
    def test_removes_only_fixed_dead_display_endpoints(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".X99-lock").write_text("       589\n")
            (root / ".X11-unix").mkdir()
            (root / "keep").write_text("profile data")
            with socket.socket(socket.AF_UNIX) as endpoint:
                endpoint.bind(str(root / ".X11-unix/X99"))
            clean_display(root)
            clean_display(root)
            self.assertFalse((root / ".X99-lock").exists())
            self.assertFalse((root / ".X11-unix/X99").exists())
            self.assertEqual((root / "keep").read_text(), "profile data")

    def test_rejects_lock_symlink_without_touching_target(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "keep"
            target.write_text("private data")
            (root / ".X99-lock").symlink_to(target)
            with self.assertRaises(ValueError):
                clean_display(root)
            self.assertEqual(target.read_text(), "private data")

    def test_rejects_socket_directory_symlink_before_removing_lock(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".X99-lock").write_text("589\n")
            (root / "elsewhere").mkdir()
            (root / ".X11-unix").symlink_to(root / "elsewhere", target_is_directory=True)
            with self.assertRaises(OSError):
                clean_display(root)
            self.assertTrue((root / ".X99-lock").exists())
