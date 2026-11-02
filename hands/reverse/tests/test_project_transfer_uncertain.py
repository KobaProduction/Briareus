"""A lost raw upload reply never replays bytes through the staged fallback."""

import tempfile
import unittest
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

import httpx
from fastmcp import FastMCP
from reverse_hand.project_transfer import register_transfer

from modules.analysis.provider import AnalysisToolProvider


class UncertainTransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_raw_upload_uncertain_does_not_repeat_staged(self) -> None:
        mcp: FastMCP[None] = FastMCP("uncertain-transfer")
        register_transfer(mcp, Mock(spec=AnalysisToolProvider))
        tool = await mcp.get_tool("upload_project_file")
        assert tool is not None
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "file.bin"
            source.write_bytes(b"abc")

            @contextmanager
            def snapshot(_path: str) -> Iterator[tuple[Path, int, str]]:
                yield source, 3, "a" * 64

            client = Mock(
                spec=httpx.AsyncClient,
                post=AsyncMock(side_effect=httpx.ReadTimeout("lost response")),
            )
            context = AsyncMock()
            context.__aenter__.return_value = client
            staged = AsyncMock()
            with (
                patch.dict("os.environ", {"BRIAREUS_PROJECT_TRANSFER": "1"}),
                patch("reverse_hand.project_transfer.source_snapshot", snapshot),
                patch("reverse_hand.project_transfer.httpx.AsyncClient", return_value=context),
                patch("reverse_hand.project_transfer._call", staged),
                self.assertRaises(httpx.ReadTimeout),
            ):
                await tool.run({"project_id": "project", "workspace_path": "file.bin"})
            staged.assert_not_awaited()
