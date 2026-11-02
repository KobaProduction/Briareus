"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

from dataclasses import dataclass as dataclass
from typing import Literal as Literal

from project_runtime_client.analysis.domain.artifacts import (
    ArtifactChunkProgress as ArtifactChunkProgress,
)
from project_runtime_client.analysis.domain.artifacts import ArtifactContent as ArtifactContent
from project_runtime_client.analysis.domain.artifacts import ImportedBinary as ImportedBinary
from project_runtime_client.analysis.domain.artifacts import ImportedProgram as ImportedProgram
from project_runtime_client.analysis.domain.artifacts import RestoredProject as RestoredProject
from project_runtime_client.analysis.domain.artifacts import (
    StagedWorkspaceArtifact as StagedWorkspaceArtifact,
)
from project_runtime_client.analysis.domain.artifacts import (
    WorkspaceArtifactExport as WorkspaceArtifactExport,
)
from project_runtime_client.analysis.domain.artifacts import (
    WorkspaceImportReceipt as WorkspaceImportReceipt,
)
