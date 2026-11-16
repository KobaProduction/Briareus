"""Persistent native analysis engine and external MCP tool forwarding."""

import logging
import os
from collections.abc import Sequence

from briareus_json_values import JsonObject
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from briareus_mcp_client.provider_tools import forwarded_tool
from briareus_server_mount import configured_mount_root
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import StdioTransport
from fastmcp.exceptions import ToolError
from fastmcp.server.providers import Provider
from fastmcp.tools import Tool
from mcp import MCPError


def engine_client() -> Client[StdioTransport]:
    return Client(
        StdioTransport(
            command="r2mcp",
            args=[],
            cwd=str(configured_mount_root()),
            env={
                "PATH": os.environ.get("PATH", "/usr/local/bin:/usr/bin:/bin"),
                "HOME": "/home/briareus",
                "R2_NOPLUGINS": "0",
            },
        ),
        timeout=300,
    )


class Radare2Provider(Provider):
    def __init__(self) -> None:
        super().__init__()
        self.pool = PersistentMcpClientPool(engine_client, name="radare2-engine", size=1)
        self.catalog: list[Tool] | None = None

    async def _call_engine_tool(self, name: str, arguments: JsonObject) -> CallToolResult:
        try:
            return await self.pool.call_tool(name, arguments)
        except MCPError as exc:
            # r2mcp rejects operations before a binary is opened with -32611.
            # This is caller state, not a failed engine or transport.
            if name == "list_files" and exc.error.code == -32611:
                raise ToolError(
                    "Use the open_file method before calling any other method",
                    log_level=logging.WARNING,
                ) from exc
            raise

    async def _list_tools(self) -> Sequence[Tool]:
        if self.catalog is None:
            tools = await self.pool.list_tools(timeout_seconds=60)
            self.catalog = [forwarded_tool(tool, self._call_engine_tool) for tool in tools]
        return self.catalog
