"""Existing private Files I/O reused independently of transport authority."""

import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from files_hand._project_files import ProjectFiles
from files_hand.application.private_receipts import (
    PrivateFileHash,
    PrivateFileRead,
)
from files_hand.domain.private_read import (
    PrivatePathAction,
    PrivatePathQuery,
    PrivateReadQuery,
    PrivateReadWindow,
)
from files_hand.presentation.private_call import FilesCall
from mcp.types import CallToolRequestParams

from modules.project_runtime.workspace_roots import ProjectFileError
from runtime_peer.private_file_receipts import PrivateFileList


class ProjectFilesTests(unittest.TestCase):
    def test_read_list_hash_and_confinement(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "data"
            root.mkdir(mode=0o700)
            target = root / "hello.txt"
            target.write_bytes(b"project fixture")
            target.chmod(0o600)
            outside = Path(folder) / "outside.txt"
            outside.write_bytes(b"must remain outside")
            (root / "escape").symlink_to(outside)
            files = ProjectFiles(root)
            try:
                result = files.execute(PrivateReadQuery("hello.txt", PrivateReadWindow(1, 3)))
                assert isinstance(result, PrivateFileRead)
                self.assertEqual(base64.b64decode(result.data_base64), b"roj")
                digest = files.execute(PrivatePathQuery("hello.txt", PrivatePathAction.HASH))
                assert isinstance(digest, PrivateFileHash)
                self.assertEqual(digest.sha256, hashlib.sha256(b"project fixture").hexdigest())
                listing = files.execute(PrivatePathQuery("", PrivatePathAction.LIST))
                assert isinstance(listing, PrivateFileList)
                self.assertEqual([row.name for row in listing.entries], ["hello.txt"])
                for path in [
                    "../outside.txt",
                    "/etc/passwd",
                    "escape",
                    "./hello.txt",
                    "hello.txt/../hello.txt",
                ]:
                    with self.assertRaises((ValueError, OSError, ProjectFileError)):
                        files.execute(PrivateReadQuery(path))
                for arguments in [
                    {"path": "hello.txt", "offset": True},
                    {"path": "hello.txt", "offset": 2**100},
                    {"path": "hello.txt", "length": 262145},
                    {"path": "hello.txt", "unknown": True},
                ]:
                    with self.assertRaises(ValueError):
                        query = FilesCall(
                            permit="fixture-" * 10,
                            call=CallToolRequestParams(name="file_read", arguments=arguments),
                        ).query()
                        files.execute(query)
                os.link(target, root / "second-link")
                with self.assertRaises(ValueError):
                    files.execute(PrivateReadQuery("hello.txt"))
            finally:
                files.close()

    def test_public_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "public"
            root.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                ProjectFiles(root)
