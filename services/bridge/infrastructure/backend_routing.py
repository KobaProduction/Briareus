"""Persistent MCP sessions, bounded catalogue cache and SDK decoding."""

from __future__ import annotations

import asyncio
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from fastmcp.client.client import CallToolResult
from mcp.types import CallToolRequestParams, Tool
from opentelemetry import trace

from .backend_sessions import BackendClientSession
from .sdk_session import BackendTarget


@dataclass(frozen=True)
class BackendDescriptor[LifespanT]:
    name: str
    url: BackendTarget[LifespanT]
    public_path: str
    purpose: str


class BackendSessionGateway:
    def __init__[LifespanT](
        self,
        backends: tuple[BackendDescriptor[LifespanT], ...],
        *,
        timeout_provider: Callable[[], Awaitable[float]] | None = None,
    ) -> None:
        self._timeout_provider = timeout_provider
        self._sessions = {
            backend.name: BackendClientSession(backend.url, name=backend.name)
            for backend in backends
        }
        self._catalog_cache: dict[str, tuple[float, tuple[Tool, ...]]] = {}
        self._catalog_locks = {name: asyncio.Lock() for name in self._sessions}
        self._catalog_ttl_seconds = 30.0

    async def _timeout_seconds(self) -> float:
        if self._timeout_provider is None:
            return 5.0
        try:
            async with asyncio.timeout(5.0):
                seconds = float(await self._timeout_provider())
            return min(300.0, max(1.0, seconds)) if math.isfinite(seconds) else 5.0
        except Exception:
            return 5.0

    def _cached_tools(self, name: str, *, refresh: bool) -> tuple[Tool, ...] | None:
        cached = self._catalog_cache.get(name)
        if not refresh and cached is not None and cached[0] > time.monotonic():
            return cached[1]
        return None

    @staticmethod
    def _catalog_span(name: str, *, hit: bool) -> None:
        span = trace.get_current_span()
        span.set_attribute("mcp.backend", name)
        span.set_attribute("mcp.backend.catalog_cache_hit", hit)

    async def tool_count(self, name: str) -> int:
        return len(await self.catalog(name, refresh=False))

    async def catalog(self, name: str, *, refresh: bool) -> tuple[Tool, ...]:
        cached = self._cached_tools(name, refresh=refresh)
        if cached is not None:
            self._catalog_span(name, hit=True)
            return cached
        async with self._catalog_locks[name]:
            cached = self._cached_tools(name, refresh=refresh)
            if cached is not None:
                self._catalog_span(name, hit=True)
                return cached
            self._catalog_span(name, hit=False)
            raw = await self._sessions[name].list_tools(await self._timeout_seconds())
            tools = tuple(raw)
            self._catalog_cache[name] = (time.monotonic() + self._catalog_ttl_seconds, tools)
            return tools

    async def invoke(self, name: str, request: CallToolRequestParams) -> CallToolResult:
        trace.get_current_span().set_attribute("mcp.backend", name)
        return await self._sessions[name].call_tool(request, await self._timeout_seconds())

    async def close(self) -> None:
        await asyncio.gather(*(session.close() for session in self._sessions.values()))
