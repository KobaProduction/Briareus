"""Existing private Files I/O reused independently of transport authority."""
import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from files_hand._project_files import ProjectFiles
from modules.project_runtime.workspace_roots import ProjectFileError


class ProjectFilesTests(unittest.TestCase):
    def test_read_list_hash_and_confinement(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"data"
            root.mkdir(mode=0o700)
            target=root/"hello.txt"
            target.write_bytes(b"project fixture")
            target.chmod(0o600)
            outside=Path(folder)/"outside.txt"
            outside.write_bytes(b"must remain outside")
            (root/"escape").symlink_to(outside)
            files=ProjectFiles(root)
            try:
                result=files.execute("file_read",{"path":"hello.txt","offset":1,"length":3})
                self.assertEqual(base64.b64decode(result["data_base64"]),b"roj")
                self.assertEqual(files.execute("file_hash",{"path":"hello.txt"})["sha256"],
                                 hashlib.sha256(b"project fixture").hexdigest())
                self.assertEqual([row["name"] for row in files.execute("file_list",{})["entries"]],["hello.txt"])
                for path in ["../outside.txt","/etc/passwd","escape","./hello.txt","hello.txt/../hello.txt"]:
                    with self.assertRaises((ValueError,OSError,ProjectFileError)):
                        files.execute("file_read",{"path":path})
                for arguments in [{"path":"hello.txt","offset":True},{"path":"hello.txt","offset":2**100},
                                  {"path":"hello.txt","length":262145},{"path":"hello.txt","unknown":True}]:
                    with self.assertRaises(ValueError):
                        files.execute("file_read",arguments)
                os.link(target,root/"second-link")
                with self.assertRaises(ValueError):
                    files.execute("file_read",{"path":"hello.txt"})
            finally:
                files.close()

    def test_public_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)/"public"
            root.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                ProjectFiles(root)
