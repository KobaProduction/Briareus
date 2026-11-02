"""Actual SDK transport keeps directory and Node ingest fields unwrapped."""

import hashlib
import tempfile
import unittest
from pathlib import Path

from fastmcp import Client, FastMCP
from files_hand.application.workspace_receipts import NodeIngestReceipt
from files_hand.presentation.tool_registry import McpFilesToolRegistry
from mcp.types import ToolAnnotations

from modules.files.file_tools import register_file_tools
from modules.files.models import ClientFile
from modules.files.workspace_store import WorkspaceFileStore


class FilesSdkReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_dispatch_preserves_no_mime_node_receipt_and_flat_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkspaceFileStore(Path(temporary) / "workspace")
            store.mkdir("directory")
            store.write_text("data.txt", "abc")
            digest = hashlib.sha256(b"abc").hexdigest()
            calls: list[tuple[str, str, int | None, str, bool]] = []

            def ingest(
                *,
                file: ClientFile,
                destination: str,
                expected_size: int | None = None,
                expected_sha256: str = "",
                overwrite: bool = False,
            ) -> NodeIngestReceipt:
                calls.append(
                    (file.download_url, destination, expected_size, expected_sha256, overwrite)
                )
                return NodeIngestReceipt(
                    path=destination, name="data.txt", size_bytes=3, modified_at_ns=1, sha256=digest
                )

            mcp = FastMCP("typed-node-files-receipts")
            annotations = ToolAnnotations()
            register_file_tools(
                McpFilesToolRegistry(mcp),
                annotations,
                annotations,
                annotations,
                workspace=store,
                max_file_bytes=1024,
                ingest_file=ingest,
            )
            async with Client(mcp) as client:
                directory = await client.call_tool("file_info", {"path": "directory"})
                listing = await client.call_tool("file_list", {})
                read = await client.call_tool("file_read", {"path": "data.txt"})
                receipt = await client.call_tool(
                    "file_ingest",
                    {
                        "file": {"download_url": "https://example.test/fixture"},
                        "destination": "data.txt",
                        "expected_size": 3,
                        "expected_sha256": digest,
                    },
                )
            assert directory.structured_content is not None
            assert listing.structured_content is not None
            assert read.structured_content is not None
            assert receipt.structured_content is not None
            self.assertNotIn("mime_type", directory.structured_content)
            self.assertNotIn("mime_type", listing.structured_content["entries"][0])
            self.assertEqual(read.structured_content["data_base64"], "YWJj")
            self.assertEqual(
                receipt.structured_content,
                {
                    "path": "data.txt",
                    "name": "data.txt",
                    "size_bytes": 3,
                    "modified_at_ns": 1,
                    "type": "file",
                    "sha256": digest,
                    "completed": True,
                    "transport": "client-file",
                },
            )
            self.assertEqual(
                calls, [("https://example.test/fixture", "data.txt", 3, digest, False)]
            )
            for result in (directory, listing, read, receipt):
                self.assertNotIn("result", result.structured_content or {})
