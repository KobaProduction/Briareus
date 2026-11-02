"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

from fastmcp.client.client import CallToolResult as CallToolResult
from fastmcp.client.transports import StreamableHttpTransport as StreamableHttpTransport
from mcp.types import CallToolRequestParams as CallToolRequestParams
from pydantic import BaseModel as BaseModel

from common.mcp_client_pool import PersistentMcpClientPool as PersistentMcpClientPool
from common.mcp_replies import decode_mcp_reply as decode_mcp_reply
from project_runtime_client.analysis.infrastructure.artifact_client import (
    artifact_reply as artifact_reply,
)
from project_runtime_client.analysis.infrastructure.artifact_client import (
    call_artifact as call_artifact,
)

from .artifact_commands import ArtifactCommand as ArtifactCommand
