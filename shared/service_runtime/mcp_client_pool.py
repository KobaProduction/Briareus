from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from contextlib import AsyncExitStack, suppress

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import ClientTransport
from mcp.types import CallToolRequestParams, Tool
from opentelemetry import trace

type ClientFactory[TransportT: ClientTransport] = Callable[[], Client[TransportT]]


class _PersistentClient[TransportT: ClientTransport]:
    def __init__(self, factory: ClientFactory[TransportT], *, name: str) -> None:
        self.factory = factory
        self.name = name
        self.client: Client[TransportT] | None = None
        self.connected = False
        self._lifecycle: AsyncExitStack | None = None
        self.connect_count = 0
        self._connect_lock = asyncio.Lock()

    async def ensure_connected(self) -> Client[TransportT]:
        if self.connected and self.client is not None:
            trace.get_current_span().set_attribute("mcp.backend.session_reused", True)
            return self.client
        async with self._connect_lock:
            if self.connected and self.client is not None:
                trace.get_current_span().set_attribute("mcp.backend.session_reused", True)
                return self.client
            trace.get_current_span().set_attribute("mcp.backend.session_reused", False)
            client = self.factory()
            lifecycle = AsyncExitStack()
            await lifecycle.enter_async_context(client)
            self._lifecycle = lifecycle
            self.client = client
            self.connected = True
            self.connect_count += 1
            return client

    async def reset(self) -> None:
        async with self._connect_lock:
            client = self.client
            self.client = None
            lifecycle = self._lifecycle
            self._lifecycle = None
            was_connected = self.connected
            self.connected = False
            if client is not None and was_connected and lifecycle is not None:
                with suppress(Exception):
                    await lifecycle.aclose()

    async def close(self) -> None:
        await self.reset()


class PersistentMcpClientPool[TransportT: ClientTransport]:
    """Small process-lifetime pool of reusable FastMCP client sessions."""

    def __init__(
        self,
        factory: ClientFactory[TransportT],
        *,
        name: str,
        size: int = 2,
    ) -> None:
        if size < 1:
            raise ValueError("MCP client pool size must be >= 1")
        self.name = name
        self._queue: asyncio.Queue[_PersistentClient[TransportT]] = asyncio.Queue(maxsize=size)
        self._clients = tuple(
            _PersistentClient(factory, name=f"{name}-{index + 1}") for index in range(size)
        )
        for client in self._clients:
            self._queue.put_nowait(client)
        self._closed = False

    @property
    def connect_count(self) -> int:
        return sum(client.connect_count for client in self._clients)

    @property
    def size(self) -> int:
        return len(self._clients)

    async def _acquire(self) -> _PersistentClient[TransportT]:
        if self._closed:
            raise RuntimeError(f"MCP client pool is closed: {self.name}")
        started = time.monotonic()
        client = await self._queue.get()
        span = trace.get_current_span()
        span.set_attribute("mcp.backend.pool", self.name)
        span.set_attribute("mcp.backend.pool_size", self.size)
        span.set_attribute("mcp.backend.pool_wait_ms", (time.monotonic() - started) * 1000)
        return client

    def _release(self, client: _PersistentClient[TransportT]) -> None:
        if not self._closed:
            self._queue.put_nowait(client)

    async def call_tool(
        self,
        request: CallToolRequestParams,
        *,
        timeout_seconds: float | None = None,
    ) -> CallToolResult:
        lease = await self._acquire()
        try:
            client = await lease.ensure_connected()
            if timeout_seconds is None:
                return await client.call_tool(request.name, request.arguments or {})
            async with asyncio.timeout(max(1.0, timeout_seconds)):
                return await client.call_tool(
                    request.name,
                    request.arguments or {},
                    timeout=timeout_seconds,
                )
        except BaseException:
            await lease.reset()
            raise
        finally:
            self._release(lease)

    async def list_tools(self, *, timeout_seconds: float | None = None) -> list[Tool]:
        lease = await self._acquire()
        try:
            client = await lease.ensure_connected()
            if timeout_seconds is None:
                return list(await client.list_tools())
            async with asyncio.timeout(max(1.0, timeout_seconds)):
                return list(await client.list_tools())
        except BaseException:
            await lease.reset()
            raise
        finally:
            self._release(lease)

    async def close(self) -> None:
        if self._closed:
            return
        clients = [await self._queue.get() for _ in self._clients]
        self._closed = True
        await asyncio.gather(*(client.close() for client in clients), return_exceptions=True)
