"""Native descriptor transfer confinement; no browser or Core credentials."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from web_hand.project_workspace import ProjectBrowserWorkspace
from modules.project_runtime.workspace_roots import ProjectFileError


@unittest.skipUnless(hasattr(os,"getuid") and os.getuid()==1000,"Dedicated Linux tool UID fixture")
class ProjectBrowserTransferTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.base=Path(self.temporary.name)
        self.shared=self.base/"shared";self.shared.mkdir(mode=0o700)
        self.private=self.base/"private";self.private.mkdir(mode=0o700)
        self.store=ProjectBrowserWorkspace(self.shared,self.private/"staging")
    def tearDown(self):self.temporary.cleanup()

    def test_upload_download_and_screenshot_staging_are_private(self):
        source=self.shared/"input.txt";source.write_text("uploaded");source.chmod(0o600)
        with self.store.upload_source("input.txt") as staged:
            self.assertTrue(staged.is_relative_to(self.private))
            self.assertEqual(staged.read_text(),"uploaded")
            source.unlink();source.symlink_to(self.private/"cookie")
            self.assertEqual(staged.read_text(),"uploaded")
        self.assertFalse(staged.exists())
        with self.store.download_target("downloads/image.png",overwrite=False) as target:
            self.assertTrue(target.is_relative_to(self.private))
            target.write_bytes(b"PNG")
            self.assertFalse((self.shared/"downloads/image.png").exists())
        self.assertEqual((self.shared/"downloads/image.png").read_bytes(),b"PNG")
        self.assertEqual(self.store.info("downloads/image.png")["size_bytes"],3)

    def test_symlinks_hardlinks_fifo_traversal_and_commit_swap_denied(self):
        secret=self.private/"cookie";secret.write_text("private-cookie");secret.chmod(0o600)
        (self.shared/"symlink").symlink_to(secret)
        os.link(secret,self.shared/"hardlink")
        os.mkfifo(self.shared/"pipe",0o600)
        (self.shared/"dir-link").symlink_to(self.private,target_is_directory=True)
        for path in ("symlink","hardlink","pipe","../private/cookie","/etc/passwd","dir-link/cookie"):
            with self.assertRaises((OSError,ValueError,RuntimeError,ProjectFileError)):
                with self.store.upload_source(path):pass
        target=self.shared/"output"
        with self.assertRaises((OSError,ValueError,RuntimeError,ProjectFileError)):
            with self.store.download_target("output",overwrite=True) as staging:
                staging.write_text("new-content")
                target.symlink_to(secret)
        self.assertEqual(secret.read_text(),"private-cookie")
        self.assertFalse(any(p.name.startswith(".briareus-web-") for p in self.shared.iterdir()))

    def test_readonly_size_bounds_and_abort_do_not_publish(self):
        readonly=ProjectBrowserWorkspace(self.shared,self.private/"readonly",read_only=True)
        with self.assertRaises(RuntimeError):
            with readonly.download_target("new",overwrite=False):pass
        with self.assertRaises(ValueError):
            with self.store.download_target("aborted",overwrite=False) as target:
                target.write_bytes(b"partial")
                raise ValueError("browser action failed")
        self.assertFalse((self.shared/"aborted").exists())
        with patch("web_hand.project_workspace.MAX_BYTES",2):
            with self.assertRaises(RuntimeError):
                with self.store.download_target("oversize",overwrite=False) as target:target.write_bytes(b"large")
        self.assertFalse((self.shared/"oversize").exists())

if __name__ == "__main__":unittest.main()
