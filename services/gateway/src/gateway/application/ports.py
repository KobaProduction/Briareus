"""Transport-independent interfaces consumed by gateway orchestration."""

from typing import Protocol

from briareus_json_values import JsonObject
from briareus_oidc import VerifiedPrincipal
from briareus_service_discovery import DiscoverySnapshot
from fastmcp.client.client import CallToolResult
from mcp.types import Tool


class ServiceInventory(Protocol):
    async def snapshot(self, *, refresh: bool = False) -> DiscoverySnapshot: ...


class PrincipalVerifier(Protocol):
    async def verify_async(self, token: str) -> VerifiedPrincipal: ...


class BackendSession(Protocol):
    async def list_tools(self, timeout_seconds: float) -> list[Tool]: ...

    async def call_tool(
        self, tool_name: str, arguments: JsonObject, timeout_seconds: float
    ) -> CallToolResult: ...

    async def close(self) -> None: ...
