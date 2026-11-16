from __future__ import annotations

import hashlib
import io
import logging
import socket
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import call, patch

from briareus_server.files.models import ClientFile
from briareus_server.files.workspace_ingress import (
    AttachmentPrivateAddressError,
    _validate_remote_file_url,
    ingest_workspace_file,
)
from briareus_workspace.workspace_store import WorkspaceFileError, WorkspaceFileStore
from fastmcp import Client, FastMCP
from fastmcp.exceptions import FastMCPError


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

    def test_private_attachment_address_is_expected_caller_rejection(self) -> None:
        for address in ("127.0.0.1", "10.1.2.3", "169.254.169.254"):
            with (
                self.subTest(address=address),
                patch(
                    "briareus_server.files.workspace_ingress.socket.getaddrinfo",
                    return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
                ),
                self.assertRaises(AttachmentPrivateAddressError) as rejected,
            ):
                _validate_remote_file_url("https://download.example.test/file")
            self.assertIsInstance(rejected.exception, WorkspaceFileError)
            self.assertIsInstance(rejected.exception, FastMCPError)
            self.assertEqual(rejected.exception.log_level, logging.WARNING)
            self.assertIn("non-public address", str(rejected.exception))

    def test_public_attachment_address_and_dns_errors_preserve_semantics(self) -> None:
        with patch(
            "briareus_server.files.workspace_ingress.socket.getaddrinfo",
            return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
        ):
            self.assertEqual(
                _validate_remote_file_url("https://download.example.test/file").hostname,
                "download.example.test",
            )
        with (
            patch(
                "briareus_server.files.workspace_ingress.socket.getaddrinfo",
                side_effect=OSError("resolver unavailable"),
            ),
            self.assertRaises(WorkspaceFileError) as failed,
        ):
            _validate_remote_file_url("https://download.example.test/file")
        self.assertNotIsInstance(failed.exception, FastMCPError)
        self.assertEqual(str(failed.exception), "attachment hostname cannot be resolved")


class AttachmentPrivateAddressMcpContracts(unittest.IsolatedAsyncioTestCase):
    async def test_blocked_address_is_warning_but_still_mcp_tool_error(self) -> None:
        app: FastMCP[None] = FastMCP("server-ingress-validation")

        @app.tool
        def ingest_private_attachment() -> None:
            _validate_remote_file_url("https://download.example.test/file")

        with (
            patch(
                "briareus_server.files.workspace_ingress.socket.getaddrinfo",
                return_value=[(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", 443))],
            ),
            self.assertLogs("fastmcp.server.server", level="WARNING") as logs,
        ):
            async with Client(app) as client:
                response = await client.call_tool_mcp("ingest_private_attachment", {})
        self.assertTrue(response.is_error)
        self.assertIn("non-public address", str(response.content))
        self.assertEqual([entry.levelno for entry in logs.records], [logging.WARNING])
