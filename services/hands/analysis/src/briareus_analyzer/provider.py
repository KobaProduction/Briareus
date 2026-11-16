"""Analyzer forwarding layer over the independently deployed native engine."""

import logging
from collections.abc import Sequence

from briareus_json_values import JsonObject
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from briareus_mcp_client.provider_tools import forwarded_tool
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.providers import Provider
from fastmcp.tools import Tool

from .settings import AnalyzerSettings


def engine_client() -> Client[StreamableHttpTransport]:
    return Client(
        StreamableHttpTransport(
            AnalyzerSettings().backend_url,
            headers={"X-Koba-Proxy-Origin": "analysis"},
        ),
        timeout=300,
    )


class AnalyzerProvider(Provider):
    def __init__(self) -> None:
        super().__init__()
        self.pool = PersistentMcpClientPool(engine_client, name="analyzer-proxy", size=1)
        self.catalog: list[Tool] | None = None

    async def _call_engine_tool(self, name: str, arguments: JsonObject) -> CallToolResult:
        try:
            return await self.pool.call_tool(name, arguments)
        except ToolError as exc:
            # The native hand emits the caller-state WARNING; this proxy logs
            # only INFO to avoid doubling alerts while preserving the tool error.
            # Unrelated backend failures retain ERROR severity.
            if name == "list_files" and (
                "Use the open_file method before calling any other method" in str(exc)
            ):
                raise ToolError(
                    "Use the open_file method before calling any other method",
                    log_level=logging.INFO,
                ) from exc
            raise

    async def _list_tools(self) -> Sequence[Tool]:
        if self.catalog is None:
            tools = await self.pool.list_tools(timeout_seconds=60)
            self.catalog = [forwarded_tool(tool, self._call_engine_tool) for tool in tools]
        return self.catalog
