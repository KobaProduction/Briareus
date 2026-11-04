from __future__ import annotations

import asyncio
import unittest
from collections.abc import Awaitable
from types import TracebackType

from briareus_json_values import JsonObject
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from fastmcp.client.client import CallToolResult
from mcp.types import Tool


class ControlledSession:
    def __init__(self) -> None:
        self.enters = 0
        self.exits = 0
        self.started = asyncio.Event()
        self.block = False

    async def __aenter__(self) -> ControlledSession:
        self.enters += 1
        return self

    async def __aexit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        del kind, error, traceback
        self.exits += 1

    def call_tool(
        self, name: str, arguments: JsonObject | None = None, *, timeout: float | None = None
    ) -> Awaitable[CallToolResult]:
        del arguments, timeout
        return self._call_tool(name)

    async def _call_tool(self, name: str) -> CallToolResult:
        self.started.set()
        if self.block:
            await asyncio.Event().wait()
        return CallToolResult(content=[], structured_content={"name": name}, meta=None)

    async def list_tools(self) -> list[Tool]:
        return [Tool.model_validate({"name": "echo", "inputSchema": {"type": "object"}})]


class PersistentMcpPoolContracts(unittest.IsolatedAsyncioTestCase):
    async def test_sequential_catalog_and_calls_reuse_one_session(self) -> None:
        session = ControlledSession()
        pool = PersistentMcpClientPool(lambda: session, name="contract", size=1)
        try:
            self.assertEqual((await pool.list_tools())[0].name, "echo")
            self.assertEqual((await pool.call_tool("echo")).structured_content, {"name": "echo"})
            await pool.call_tool("echo")
            self.assertEqual(pool.connect_count, 1)
            self.assertEqual(session.enters, 1)
        finally:
            await pool.close()
        self.assertEqual(session.exits, 1)

    async def test_cancellation_disconnects_lease_and_restores_pool_capacity(self) -> None:
        sessions: list[ControlledSession] = []
        created = asyncio.Event()

        def create() -> ControlledSession:
            session = ControlledSession()
            session.block = not sessions
            sessions.append(session)
            created.set()
            return session

        pool = PersistentMcpClientPool(create, name="contract", size=1)
        pending = asyncio.create_task(pool.call_tool("blocked"))
        try:
            await created.wait()
            await sessions[0].started.wait()
            pending.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await pending
            self.assertEqual(sessions[0].exits, 1)
            async with asyncio.timeout(1):
                await pool.call_tool("next")
            self.assertEqual(pool.connect_count, 2)
        finally:
            pending.cancel()
            await asyncio.gather(pending, return_exceptions=True)
            await pool.close()
        self.assertEqual(sessions[1].exits, 1)
