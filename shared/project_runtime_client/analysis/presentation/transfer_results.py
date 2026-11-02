"""Serialize Analysis domain receipts at the public MCP boundary."""

from collections.abc import Callable
from typing import Literal

from mcp.types import CallToolResult
from pydantic import BaseModel, ConfigDict

from project_runtime_client.analysis.domain.artifacts import (
    ImportedBinary,
    ImportedProgram,
    RestoredProject,
    WorkspaceArtifactExport,
)
from service_runtime.mcp_dataclass_results import dataclass_result


class WorkspaceImportResult(BaseModel):
    model_config = ConfigDict(frozen=True, from_attributes=True)
    workspace_path: str
    sha256: str
    transfer_method: Literal["direct_raw", "mcp_base64"]
    direct_upload_error: str
    result: ImportedBinary | ImportedProgram | RestoredProject
    transfer_cleanup_error: str


export_result: Callable[[WorkspaceArtifactExport], CallToolResult] = dataclass_result
