from __future__ import annotations

import asyncio
import unittest
from collections.abc import Sequence

import mcp.types as mt
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from fastmcp import Client, FastMCP
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

    async def test_zero_call_budget_is_unlimited_for_proxy_and_direct_sessions(self) -> None:
        async def unlimited() -> float:
            return 0.0

        pool = ProxyClientPool(backend(), name="unlimited", timeout_provider=unlimited)
        direct = BackendClientSession(backend(), name="unlimited")
        try:
            async with await pool.acquire() as client:
                await client.list_tools()
                self.assertIsNone(client.session._session_read_timeout_seconds)
                self.assertFalse((await client.call_tool("slow_tool")).is_error)
            await direct.list_tools(timeout_seconds=0)
            self.assertFalse((await direct.call_tool("slow_tool", {}, 0)).is_error)
        finally:
            await pool.close()
            await direct.close()

    async def test_shared_pool_zero_overrides_client_default_timeout(self) -> None:
        server: FastMCP[None] = FastMCP("unlimited-call")

        @server.tool
        async def slow_tool() -> str:
            await asyncio.sleep(2.2)
            return "finished"

        pool = PersistentMcpClientPool(lambda: Client(server, timeout=2), name="unlimited")
        try:
            result = await pool.call_tool("slow_tool", timeout_seconds=0)
            self.assertFalse(result.is_error)
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
