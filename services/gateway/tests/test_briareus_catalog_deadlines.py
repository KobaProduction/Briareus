from __future__ import annotations

import asyncio
import unittest
from collections.abc import Sequence

import mcp.types as mt
from fastmcp import FastMCP
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool
from gateway.backend_sessions import BackendClientSession, ProxyClientPool
from mcp.shared.exceptions import MCPError


class SlowCatalog(Middleware):
    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        await asyncio.sleep(1.2)
        return await call_next(context)


def backend() -> FastMCP[None]:
    server: FastMCP[None] = FastMCP("catalog-deadline", middleware=[SlowCatalog()])

    @server.tool
    async def slow_tool() -> str:
        await asyncio.sleep(1.2)
        return "finished"

    return server


async def short_call_timeout() -> float:
    return 1.0


class CatalogDeadlineContracts(unittest.IsolatedAsyncioTestCase):
    async def test_proxy_catalog_can_exceed_call_budget_without_extending_tool_calls(self) -> None:
        pool = ProxyClientPool(backend(), name="test", timeout_provider=short_call_timeout)
        try:
            async with await pool.acquire() as client:
                tools = await client.list_tools()
                self.assertEqual([tool.name for tool in tools], ["slow_tool"])
                with self.assertRaises(MCPError):
                    await client.call_tool("slow_tool")
        finally:
            await pool.close()

    async def test_root_catalog_has_its_own_budget(self) -> None:
        client = BackendClientSession(backend(), name="test")
        try:
            tools = await client.list_tools(timeout_seconds=1)
            self.assertEqual([tool.name for tool in tools], ["slow_tool"])
            with self.assertRaises(MCPError):
                await client.call_tool("slow_tool", {}, timeout_seconds=1)
        finally:
            await client.close()
