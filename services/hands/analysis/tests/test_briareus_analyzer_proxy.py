from __future__ import annotations

import unittest
from unittest.mock import patch

from briareus_analyzer.provider import AnalyzerProvider
from fastmcp import Client, FastMCP


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
