from __future__ import annotations

import logging
import unittest
from unittest.mock import AsyncMock, patch

from briareus_analyzer.provider import AnalyzerProvider
from briareus_hand_runtime.tool_observability import management_audit_enabled
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from mcp.types import Tool as McpTool


class AnalyzerProxyTests(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_keeps_native_engine_state_between_tools(self) -> None:
        engine = FastMCP("native-test-engine")
        selected = ""

        @engine.tool
        async def select_artifact(path: str) -> str:
            nonlocal selected
            selected = path
            return selected

        @engine.tool
        async def describe_artifact() -> str:
            return selected

        with patch(
            "briareus_analyzer.provider.engine_client", return_value=Client(engine)
        ) as factory:
            provider = AnalyzerProvider()
        proxy = FastMCP("test-analyzer")
        proxy.add_provider(provider)
        try:
            async with Client(proxy) as client:
                tools = await client.list_tools()
                self.assertEqual(
                    {tool.name for tool in tools}, {"select_artifact", "describe_artifact"}
                )
                await client.call_tool("select_artifact", {"path": "/workspace/probe"})
                result = await client.call_tool("describe_artifact", {})
                self.assertEqual(result.data, {"result": "/workspace/probe"})
                factory.assert_called_once_with()
        finally:
            await provider.pool.close()


class AnalyzerProxyErrorClassificationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.provider = AnalyzerProvider()

    async def asyncTearDown(self) -> None:
        await self.provider.pool.close()

    async def test_proxy_preserves_expected_native_rejection(self) -> None:
        error = ToolError(
            "Error calling tool 'list_files': "
            "Use the open_file method before calling any other method"
        )
        self.provider.pool.call_tool = AsyncMock(side_effect=error)
        with self.assertRaises(ToolError) as raised:
            await self.provider._call_engine_tool("list_files", {"path": "/workspace"})
        self.assertEqual(raised.exception.log_level, logging.INFO)
        self.assertEqual(
            str(raised.exception),
            "Use the open_file method before calling any other method",
        )

    async def test_proxy_does_not_reclassify_real_failures(self) -> None:
        for tool, message in (
            ("list_files", "backend connection closed"),
            ("open_file", "Use the open_file method before calling any other method"),
        ):
            with self.subTest(tool=tool):
                error = ToolError(message)
                self.provider.pool.call_tool = AsyncMock(side_effect=error)
                with self.assertRaises(ToolError) as raised:
                    await self.provider._call_engine_tool(tool, {})
                self.assertIs(raised.exception, error)
                self.assertEqual(raised.exception.log_level, logging.ERROR)

    def test_forwarding_audits_once_at_public_proxy(self) -> None:
        self.assertFalse(management_audit_enabled("radare2", "analysis"))
        self.assertTrue(management_audit_enabled("analysis", ""))

    async def test_proxy_mcp_call_logs_info_without_duplicate_warning(self) -> None:
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
        self.provider.pool.call_tool = AsyncMock(
            side_effect=ToolError(
                "Error calling tool 'list_files': "
                "Use the open_file method before calling any other method"
            )
        )
        proxy: FastMCP[None] = FastMCP("test-analyzer")
        proxy.add_provider(self.provider)
        async with Client(proxy) as client:
            with self.assertLogs("fastmcp.server.server", level="INFO") as logged:
                response = await client.call_tool_mcp("list_files", {"path": "/workspace"})
        self.assertTrue(response.is_error)
        self.assertIn("Use the open_file method", str(response.content))
        self.assertEqual([entry.levelno for entry in logged.records], [logging.INFO])
