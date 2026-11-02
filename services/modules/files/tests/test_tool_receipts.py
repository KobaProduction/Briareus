"""Actual SDK dispatch preserves flat Files receipts over typed store results."""

import base64
import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastmcp import Client, FastMCP
from mcp.types import ToolAnnotations

from modules.files.file_tools import register_file_tools
from modules.files.presentation.tool_registry import McpFilesToolRegistry
from modules.files.receipts import WorkspaceIngestReceipt
from modules.files.workspace_store import WorkspaceFileStore


class FilesSdkReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_sdk_info_list_read_and_ingest_keep_flat_wire_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = WorkspaceFileStore(Path(temporary) / "workspace")
            store.mkdir("directory")
            entry = store.write_text("data.txt", "abc")
            digest = hashlib.sha256(b"abc").hexdigest()
            ingested = WorkspaceIngestReceipt(
                path=entry.path,
                name=entry.name,
                size_bytes=entry.size_bytes,
                modified_at_ns=entry.modified_at_ns,
                mime_type="text/plain",
                sha256=digest,
            )
            mcp: FastMCP[None] = FastMCP("typed-files-receipts")
            annotations = ToolAnnotations()
            register_file_tools(
                McpFilesToolRegistry(mcp),
                annotations,
                annotations,
                annotations,
                workspace=store,
                max_file_bytes=1024,
            )
            with patch("modules.files.file_tools.ingest_workspace_file", return_value=ingested):
                async with Client(mcp) as client:
                    directory = await client.call_tool("file_info", {"path": "directory"})
                    listing = await client.call_tool("file_list", {})
                    read = await client.call_tool("file_read", {"path": "data.txt"})
                    ingest = await client.call_tool(
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
            assert ingest.structured_content is not None
            self.assertEqual(directory.structured_content["type"], "directory")
            self.assertNotIn("mime_type", directory.structured_content)
            self.assertEqual(listing.structured_content["entries"][0]["type"], "directory")
            self.assertNotIn("mime_type", listing.structured_content["entries"][0])
            self.assertEqual(base64.b64decode(read.structured_content["data_base64"]), b"abc")
            self.assertEqual(read.structured_content["next_offset"], 3)
            self.assertEqual(ingest.structured_content["sha256"], digest)
            self.assertIs(ingest.structured_content["completed"], True)
            for result in (directory, listing, read, ingest):
                self.assertNotIn("result", result.structured_content or {})
