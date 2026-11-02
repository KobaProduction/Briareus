"""Concrete artifact replies decoded only at the private MCP transport boundary."""

from fastmcp.client.client import CallToolResult
from fastmcp.client.transports import StreamableHttpTransport
from mcp.types import CallToolRequestParams
from pydantic import BaseModel

from service_runtime.mcp_client_pool import PersistentMcpClientPool
from service_runtime.mcp_replies import decode_mcp_reply

from .artifact_commands import ArtifactCommand


def artifact_reply[T: BaseModel](result: CallToolResult, response_type: type[T], tool: str) -> T:
    return decode_mcp_reply(
        result, response_type, context=f"Analysis transfer {tool}", unwrap_data=False
    )


async def call_artifact[T: BaseModel](
    pool: PersistentMcpClientPool[StreamableHttpTransport],
    command: ArtifactCommand,
    response_type: type[T],
) -> T:
    result = await pool.call_tool(
        CallToolRequestParams(name=command.tool_name, arguments=command.model_dump(mode="json"))
    )
    return artifact_reply(result, response_type, command.tool_name)
