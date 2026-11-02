"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import json as json
from dataclasses import asdict as asdict
from typing import Literal as Literal

from mcp.types import CallToolResult as CallToolResult
from mcp.types import TextContent as TextContent
from pydantic import BaseModel as BaseModel
from pydantic import ConfigDict as ConfigDict

from modules.analysis.domain.artifacts import ImportedBinary as ImportedBinary
from modules.analysis.domain.artifacts import ImportedProgram as ImportedProgram
from modules.analysis.domain.artifacts import RestoredProject as RestoredProject
from modules.analysis.domain.artifacts import WorkspaceArtifactExport as WorkspaceArtifactExport
from project_runtime_client.analysis.presentation.transfer_results import (
    WorkspaceImportResult as WorkspaceImportResult,
)
from project_runtime_client.analysis.presentation.transfer_results import (
    export_result as export_result,
)
