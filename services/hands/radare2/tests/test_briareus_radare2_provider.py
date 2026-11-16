from __future__ import annotations

import logging
import unittest
from unittest.mock import AsyncMock

from briareus_radare2.provider import Radare2Provider
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp import MCPError
from mcp.types import Tool as McpTool


class Radare2ErrorClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.provider = Radare2Provider()

    async def asyncTearDown(self) -> None:
        await self.provider.pool.close()

    async def test_native_no_open_file_is_a_caller_rejection(self) -> None:
        self.provider.pool.call_tool = AsyncMock(side_effect=MCPError(-32611, "-32611"))
        with self.assertRaises(ToolError) as raised:
            await self.provider._call_engine_tool("list_files", {"path": "/workspace"})
        self.assertEqual(raised.exception.log_level, logging.WARNING)
        self.assertEqual(
            str(raised.exception),
            "Use the open_file method before calling any other method",
        )
        self.provider.pool.call_tool.assert_awaited_once_with("list_files", {"path": "/workspace"})

    async def test_native_other_codes_or_tools_remain_failures(self) -> None:
        for tool, code in (("list_files", -32001), ("open_file", -32611)):
            with self.subTest(tool=tool, code=code):
                error = MCPError(code, f"backend failure {code}")
                self.provider.pool.call_tool = AsyncMock(side_effect=error)
                with self.assertRaises(MCPError) as raised:
                    await self.provider._call_engine_tool(tool, {})
                self.assertIs(raised.exception, error)

    async def test_native_transport_failure_remains_a_failure(self) -> None:
        error = TimeoutError("engine did not respond")
        self.provider.pool.call_tool = AsyncMock(side_effect=error)
        with self.assertRaises(TimeoutError) as raised:
            await self.provider._call_engine_tool("list_files", {})
        self.assertIs(raised.exception, error)

    async def test_native_mcp_call_logs_warning_and_preserves_tool_error(self) -> None:
        tool = McpTool(
            name="list_files",
            description="List the selected file's directory",
            inputSchema={
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
        )
        self.provider.pool.list_tools = AsyncMock(return_value=[tool])
        self.provider.pool.call_tool = AsyncMock(side_effect=MCPError(-32611, "-32611"))
        mcp: FastMCP[None] = FastMCP("test-radare2")
        mcp.add_provider(self.provider)
        async with Client(mcp) as client:
            with self.assertLogs("fastmcp.server.server", level="WARNING") as logged:
                response = await client.call_tool_mcp("list_files", {"path": "/workspace"})
        self.assertTrue(response.is_error)
        self.assertIn("Use the open_file method", str(response.content))
        self.assertEqual([entry.levelno for entry in logged.records], [logging.WARNING])
