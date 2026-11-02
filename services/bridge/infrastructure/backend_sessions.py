"""Concurrent calls share one lazily connected backend MCP session."""

from __future__ import annotations

import asyncio
import time

from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import ClientTransport
from mcp.types import CallToolRequestParams, Tool
from opentelemetry import trace

from .sdk_session import BackendTarget, SdkSessionLifecycle


class BackendClientSession:
    """Lazy persistent FastMCP client for root bridge forwarding."""

    def __init__[LifespanT](self, target: BackendTarget[LifespanT], *, name: str) -> None:
        self.name = name
        self._client = Client[ClientTransport](
            target,
            name=f"bridge-{name}-backend",
            timeout=300,
            mode="auto",
            cache=True,
        )
        self._sdk_lifecycle: SdkSessionLifecycle = self._client
        self._connect_lock = asyncio.Lock()
        self._call_lock = asyncio.Lock()
        self._calls_active = 0
        self._closing = False
        self._connected = False
        self.connect_count = 0

    async def _enter_call(self) -> None:
        async with self._call_lock:
            if self._closing:
                raise RuntimeError(f"backend client session closing: {self.name}")
            self._calls_active += 1

    async def _exit_call(self) -> None:
        async with self._call_lock:
            self._calls_active -= 1

    async def _ensure_connected(self, timeout_seconds: float) -> None:
        task = self._client._session_state.session_task
        dead = task is not None and task.done()
        if self._connected and not dead:
            trace.get_current_span().set_attribute("mcp.backend.session_reused", True)
            return
        async with self._connect_lock:
            task = self._client._session_state.session_task
            dead = task is not None and task.done()
            if self._connected and not dead:
                trace.get_current_span().set_attribute("mcp.backend.session_reused", True)
                return
            trace.get_current_span().set_attribute("mcp.backend.session_reused", False)
            if self._connected:
                try:
                    async with asyncio.timeout(5.0):
                        await self._sdk_lifecycle._disconnect(force=True)
                finally:
                    self._connected = False
            async with asyncio.timeout(max(1.0, timeout_seconds)):
                await self._sdk_lifecycle._connect()
            self._connected = True
            self.connect_count += 1

    async def list_tools(self, timeout_seconds: float) -> list[Tool]:
        await self._enter_call()
        try:
            await self._ensure_connected(timeout_seconds)
            async with asyncio.timeout(max(1.0, timeout_seconds)):
                return list(await self._client.list_tools())
        finally:
            await self._exit_call()

    async def call_tool(
        self,
        request: CallToolRequestParams,
        timeout_seconds: float,
    ) -> CallToolResult:
        await self._enter_call()
        try:
            await self._ensure_connected(timeout_seconds)
            return await self._client.call_tool(
                request.name,
                request.arguments or {},
                timeout=timeout_seconds,
            )
        except BaseException:
            task = self._client._session_state.session_task
            if task is not None and task.done():
                async with self._connect_lock:
                    if self._connected:
                        try:
                            async with asyncio.timeout(5.0):
                                await self._sdk_lifecycle._disconnect(force=True)
                        finally:
                            self._connected = False
            raise
        finally:
            await self._exit_call()

    async def close(self) -> None:
        async with self._call_lock:
            self._closing = True
        deadline = time.monotonic() + 5.0
        while True:
            async with self._call_lock:
                active = self._calls_active
            if not active:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                # Keep closing=True; a subsequent close may finish after the
                # client returns, without interrupting an unknown mutation.
                raise RuntimeError(f"backend client has active calls: {self.name}")
            await asyncio.sleep(min(0.05, remaining))
        async with self._connect_lock:
            if not self._connected:
                return
            try:
                async with asyncio.timeout(5.0):
                    await self._sdk_lifecycle._disconnect(force=True)
            finally:
                self._connected = False
