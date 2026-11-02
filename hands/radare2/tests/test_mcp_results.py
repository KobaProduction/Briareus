"""Typed receipts retain the existing top-level MCP shape across actual SDK dispatch."""

import base64
import hashlib
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

from fastmcp import Client, FastMCP
from radare2_hand.domain.commands import AnalyzerCommand
from radare2_hand.runtime import Analyzer, AnalyzerResult
from radare2_hand.tools import register_tools


@dataclass(frozen=True, slots=True)
class Deadline:
    expires_at: float | None = None


class McpReceiptTests(unittest.IsolatedAsyncioTestCase):
    async def test_import_receipts_and_idempotent_finish_keep_original_wire(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            analyzer = Analyzer(Path(temporary))

            async def execute(command: AnalyzerCommand) -> AnalyzerResult:
                return await analyzer.execute(command, Deadline())

            mcp: FastMCP[None] = FastMCP("radare-receipt-test")
            register_tools(mcp, execute)
            data = b"immutable binary fixture"
            async with Client(mcp) as client:
                catalogue = await client.list_tools()
                self.assertEqual(len(catalogue), 11)
                started = await client.call_tool(
                    "radare2_import_start",
                    {
                        "name": "fixture.bin",
                        "sha256": hashlib.sha256(data).hexdigest(),
                        "size": len(data),
                    },
                )
                assert started.structured_content is not None
                upload = started.structured_content["upload_id"]
                self.assertIsInstance(upload, str)
                self.assertEqual(
                    set(started.structured_content), {"upload_id", "size", "chunk_bytes", "offset"}
                )
                written = await client.call_tool(
                    "radare2_import_chunk",
                    {
                        "upload_id": upload,
                        "offset": 0,
                        "content_base64": base64.b64encode(data).decode(),
                    },
                )
                assert written.structured_content is not None
                self.assertEqual(written.structured_content["offset"], len(data))
                committed = await client.call_tool("radare2_import_finish", {"upload_id": upload})
                assert committed.structured_content is not None
                self.assertEqual(committed.structured_content["binary_id"], upload)
                self.assertEqual(
                    committed.structured_content["sha256"], hashlib.sha256(data).hexdigest()
                )
                retried = await client.call_tool("radare2_import_finish", {"upload_id": upload})
                self.assertEqual(retried.structured_content, committed.structured_content)
                listed = await client.call_tool("radare2_list_binaries", {})
                self.assertEqual(
                    listed.structured_content, {"binaries": [committed.structured_content]}
                )
            await analyzer.close()
