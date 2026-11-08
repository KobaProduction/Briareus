from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import cast

from briareus_json_values import JsonObject, JsonValue, json_object, json_value
from fastmcp.client.client import CallToolResult
from mcp.types import Tool
from opentelemetry import trace

from .application.ports import BackendSession
from .backend_contracts import (
    AvailableTools,
    BackendCallFailure,
    BackendCallSuccess,
    BackendInventory,
    BackendStatus,
    RemoteToolDescription,
    UnavailableTools,
)
from .backend_sessions import BackendClientSession, BackendTarget


@dataclass(frozen=True)
class BackendDescriptor:
    name: str
    url: BackendTarget
    public_path: str
    purpose: str


def _tool_public(tool: Tool) -> RemoteToolDescription:
    return RemoteToolDescription(
        name=tool.name,
        description=tool.description or "",
        title=tool.title or None,
        input_schema=json_object(tool.input_schema, context=f"{tool.name} inputSchema"),
        output_schema=(
            json_object(tool.output_schema, context=f"{tool.name} outputSchema")
            if tool.output_schema is not None
            else None
        ),
    )


def _decode_call_result(result: CallToolResult) -> JsonValue:
    # These are extension payloads owned by the remote tool, not gateway records.
    for value in (result.structured_content, result.data):
        if value is not None:
            return json_value(cast(object, value), context="backend tool result")
    blocks: list[JsonValue] = [block.text for block in result.content if block.type == "text"]
    return blocks or None


class BackendRouter:
    def __init__(
        self,
        backends: tuple[BackendDescriptor, ...],
        *,
        timeout_provider: Callable[[], Awaitable[float]] | None = None,
    ) -> None:
        self._backends = {backend.name: backend for backend in backends}
        self._timeout_provider = timeout_provider
        self._sessions: dict[str, BackendSession] = {
            name: BackendClientSession(backend.url, name=name)
            for name, backend in self._backends.items()
        }
        self._catalog_cache: dict[str, tuple[float, list[Tool]]] = {}
        self._catalog_locks = {name: asyncio.Lock() for name in self._backends}
        self._catalog_ttl_seconds = 30.0

    async def _timeout_seconds(self) -> float:
        if self._timeout_provider is None:
            return 0.0
        try:
            return max(0.0, float(await self._timeout_provider()))
        except Exception:
            return 0.0

    def _get(self, name: str) -> BackendDescriptor:
        key = name.strip().casefold()
        backend = self._backends.get(key)
        if backend is None:
            raise ValueError(f"unknown backend {name!r}; expected one of {sorted(self._backends)}")
        return backend

    async def _catalog(
        self,
        backend: BackendDescriptor,
        *,
        refresh: bool = False,
    ) -> list[Tool]:
        now = time.monotonic()
        cached = self._catalog_cache.get(backend.name)
        if not refresh and cached is not None and cached[0] > now:
            span = trace.get_current_span()
            span.set_attribute("mcp.backend", backend.name)
            span.set_attribute("mcp.backend.catalog_cache_hit", True)
            return cached[1]
        async with self._catalog_locks[backend.name]:
            now = time.monotonic()
            cached = self._catalog_cache.get(backend.name)
            if not refresh and cached is not None and cached[0] > now:
                span = trace.get_current_span()
                span.set_attribute("mcp.backend", backend.name)
                span.set_attribute("mcp.backend.catalog_cache_hit", True)
                return cached[1]
            span = trace.get_current_span()
            span.set_attribute("mcp.backend", backend.name)
            span.set_attribute("mcp.backend.catalog_cache_hit", False)
            timeout = await self._timeout_seconds()
            raw = await self._sessions[backend.name].list_tools(timeout)
            tools = list(raw)
            self._catalog_cache[backend.name] = (
                now + self._catalog_ttl_seconds,
                tools,
            )
            return tools

    async def describe(self) -> BackendInventory:
        async def probe(backend: BackendDescriptor) -> BackendStatus:
            try:
                tools = await self._catalog(backend)
            except Exception as exc:
                return BackendStatus(
                    name=backend.name,
                    public_path=backend.public_path,
                    purpose=backend.purpose,
                    status="not_available",
                    tool_count=0,
                    error_type=type(exc).__name__,
                )
            return BackendStatus(
                name=backend.name,
                public_path=backend.public_path,
                purpose=backend.purpose,
                status="available",
                tool_count=len(tools),
            )

        values = await asyncio.gather(*(probe(backend) for backend in self._backends.values()))
        return BackendInventory(backends=list(values), count=len(values))

    async def tools(self, name: str, *, refresh: bool = False) -> AvailableTools | UnavailableTools:
        backend = self._get(name)
        try:
            tools = await self._catalog(backend, refresh=refresh)
        except Exception as exc:
            return UnavailableTools(
                backend=backend.name,
                public_path=backend.public_path,
                error_type=type(exc).__name__,
            )
        return AvailableTools(
            backend=backend.name,
            public_path=backend.public_path,
            tools=[_tool_public(tool) for tool in tools],
            count=len(tools),
        )

    async def call(
        self,
        name: str,
        tool_name: str,
        arguments: JsonObject | None = None,
    ) -> BackendCallSuccess | BackendCallFailure:
        backend = self._get(name)
        span = trace.get_current_span()
        span.set_attribute("mcp.backend", backend.name)
        try:
            timeout = await self._timeout_seconds()
            result = await self._sessions[backend.name].call_tool(
                tool_name, arguments or {}, timeout
            )
        except Exception as exc:
            message = str(exc)[:1000]
            timed_out = "timed out" in message.casefold() or isinstance(exc, TimeoutError)
            return BackendCallFailure(
                backend=backend.name,
                tool=tool_name,
                error_type="MCP_BACKEND_TIMEOUT" if timed_out else type(exc).__name__,
                message=message,
                hint=(
                    "Retry, narrow the request, or use an asynchronous job tool when available."
                    if timed_out
                    else ""
                ),
            )
        return BackendCallSuccess(
            backend=backend.name, tool=tool_name, result=_decode_call_result(result)
        )

    async def close(self) -> None:
        await asyncio.gather(*(session.close() for session in self._sessions.values()))
