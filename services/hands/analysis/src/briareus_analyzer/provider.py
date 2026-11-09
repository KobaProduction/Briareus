"""Analyzer forwarding layer over the independently deployed native engine."""

from collections.abc import Sequence

from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from briareus_mcp_client.provider_tools import forwarded_tool
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
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

    async def _list_tools(self) -> Sequence[Tool]:
        if self.catalog is None:
            tools = await self.pool.list_tools(timeout_seconds=60)
            self.catalog = [forwarded_tool(tool, self.pool.call_tool) for tool in tools]
        return self.catalog
