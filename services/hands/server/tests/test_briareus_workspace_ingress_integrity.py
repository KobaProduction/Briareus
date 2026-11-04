from __future__ import annotations

import hashlib
import io
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import call, patch

from briareus_server.files.models import ClientFile
from briareus_server.files.workspace_ingress import ingest_workspace_file
from briareus_workspace.workspace_store import WorkspaceFileError, WorkspaceFileStore


class AttachmentResponse(io.BytesIO):
    def __init__(self, data: bytes, declared_size: int | None = None) -> None:
        super().__init__(data)
        self.headers = Message()
        if declared_size is not None:
            self.headers["Content-Length"] = str(declared_size)

    def geturl(self) -> str:
        return "https://download.example.test/redirected"


class WorkspaceIngressIntegrityContracts(unittest.TestCase):
    def test_download_verifies_size_digest_and_final_url_before_atomic_publication(self) -> None:
        data = b"exact attachment\x00bytes"
        digest = hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as directory:
            workspace = WorkspaceFileStore(Path(directory))
            with (
                patch(
                    "briareus_server.files.workspace_ingress._open_remote_file",
                    return_value=AttachmentResponse(data, len(data)),
                ),
                patch(
                    "briareus_server.files.workspace_ingress._validate_remote_file_url"
                ) as validate,
            ):
                result = ingest_workspace_file(
                    ClientFile(download_url="https://download.example.test/original"),
                    "attachment.bin",
                    expected_size=len(data),
                    expected_sha256=digest,
                    workspace=workspace,
                    max_bytes=1024,
                )
            self.assertEqual((Path(directory) / "attachment.bin").read_bytes(), data)
            self.assertEqual(result["sha256"], digest)
            self.assertTrue(result["completed"])
            self.assertEqual(
                validate.call_args_list,
                [
                    call("https://download.example.test/original"),
                    call("https://download.example.test/redirected"),
                ],
            )
            self.assertEqual([path.name for path in Path(directory).iterdir()], ["attachment.bin"])

    def test_stream_overflow_and_hash_failure_preserve_existing_file_and_remove_partial(
        self,
    ) -> None:
        for failure in ("overflow", "hash"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "attachment.bin").write_bytes(b"original")
                with (
                    patch(
                        "briareus_server.files.workspace_ingress._open_remote_file",
                        return_value=AttachmentResponse(b"downloaded"),
                    ),
                    patch("briareus_server.files.workspace_ingress._validate_remote_file_url"),
                    self.assertRaises(WorkspaceFileError),
                ):
                    ingest_workspace_file(
                        ClientFile(download_url="https://download.example.test/file"),
                        "attachment.bin",
                        overwrite=True,
                        expected_sha256="0" * 64 if failure == "hash" else "",
                        workspace=WorkspaceFileStore(root),
                        max_bytes=4 if failure == "overflow" else 1024,
                    )
                self.assertEqual((root / "attachment.bin").read_bytes(), b"original")
                self.assertEqual([path.name for path in root.iterdir()], ["attachment.bin"])
