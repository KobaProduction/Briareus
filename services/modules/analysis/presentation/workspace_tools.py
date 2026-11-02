"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

from fastmcp import FastMCP as FastMCP
from mcp.types import CallToolResult as CallToolResult

from modules.analysis.application.workspace_transfers import (
    WorkspaceTransfers as WorkspaceTransfers,
)
from project_runtime_client.analysis.presentation.workspace_tools import (
    register_workspace_transfer_tools as register_workspace_transfer_tools,
)

from .transfer_results import WorkspaceImportResult as WorkspaceImportResult
from .transfer_results import export_result as export_result
