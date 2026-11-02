"""Browser transfer receipts retain their top-level shape through the real MCP SDK."""

import json
import unittest

from fastmcp import Client, FastMCP
from mcp.types import CallToolResult, TextContent

from modules.web.models import BrowserDownload
from modules.web.transfer_presenter import present_browser_transfer
from modules.workspace_compat.domain.receipts import WorkspaceDirectoryEntry, WorkspaceFileEntry


class BrowserTransferContracts(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_download_keeps_top_level_typed_file_receipt(self) -> None:
        file = WorkspaceFileEntry(
            path="downloads/fixture.bin",
            name="fixture.bin",
            size_bytes=8,
            modified_at_ns=123456789,
            mime_type="application/octet-stream",
        )
        server: FastMCP[None] = FastMCP("browser-transfer-receipt")

        @server.tool()
        async def download_receipt() -> CallToolResult:
            return present_browser_transfer(BrowserDownload(file, "browser-name.bin"))

        async with Client(server) as client:
            result = await client.call_tool("download_receipt", {})
        content = result.structured_content
        self.assertEqual(
            content,
            {
                "path": "downloads/fixture.bin",
                "name": "fixture.bin",
                "type": "file",
                "size_bytes": 8,
                "modified_at_ns": 123456789,
                "mime_type": "application/octet-stream",
                "suggested_filename": "browser-name.bin",
            },
        )
        texts = [block.text for block in result.content if isinstance(block, TextContent)]
        self.assertEqual(len(texts), 1)
        self.assertEqual(json.loads(texts[0]), content)
        self.assertFalse(result.is_error)

    def test_screenshot_receipt_does_not_invent_download_or_private_fields(self) -> None:
        file = WorkspaceFileEntry(
            path="screenshots/capture.png",
            name="capture.png",
            size_bytes=42,
            modified_at_ns=987654321,
            mime_type="image/png",
        )
        result = present_browser_transfer(file)
        self.assertEqual(
            result.structured_content,
            {
                "path": "screenshots/capture.png",
                "name": "capture.png",
                "type": "file",
                "size_bytes": 42,
                "modified_at_ns": 987654321,
                "mime_type": "image/png",
            },
        )

    def test_directory_receipt_keeps_directory_shape(self) -> None:
        directory = WorkspaceDirectoryEntry(
            path="downloads", name="downloads", size_bytes=0, modified_at_ns=123
        )
        result = present_browser_transfer(directory)
        self.assertEqual(
            result.structured_content,
            {
                "path": "downloads",
                "name": "downloads",
                "type": "directory",
                "size_bytes": 0,
                "modified_at_ns": 123,
            },
        )
