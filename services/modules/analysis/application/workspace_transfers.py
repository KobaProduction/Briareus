"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

from typing import Protocol as Protocol

from modules.analysis.domain.artifacts import WorkspaceArtifactExport as WorkspaceArtifactExport
from modules.analysis.domain.artifacts import WorkspaceImportReceipt as WorkspaceImportReceipt
from project_runtime_client.analysis.application.workspace_transfers import (
    WorkspaceTransfers as WorkspaceTransfers,
)
