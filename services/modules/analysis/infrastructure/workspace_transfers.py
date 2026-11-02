"""Compatibility exports for the shared Analysis client implementation."""

from __future__ import annotations

import base64 as base64
import binascii as binascii
import uuid as uuid
from collections.abc import AsyncIterator as AsyncIterator
from contextlib import suppress as suppress
from dataclasses import replace as replace
from pathlib import Path as Path

import httpx as httpx
from fastmcp import Client as Client
from fastmcp.client.transports import StreamableHttpTransport as StreamableHttpTransport
from pydantic import BaseModel as BaseModel

from common.mcp_client_pool import PersistentMcpClientPool as PersistentMcpClientPool
from common.settings import AnalysisSettings as AnalysisSettings
from modules.analysis.application.workspace_transfers import (
    WorkspaceTransfers as WorkspaceTransfers,
)
from modules.analysis.domain.artifacts import ArtifactContent as ArtifactContent
from modules.analysis.domain.artifacts import StagedWorkspaceArtifact as StagedWorkspaceArtifact
from modules.analysis.domain.artifacts import WorkspaceArtifactExport as WorkspaceArtifactExport
from modules.analysis.domain.artifacts import WorkspaceImportReceipt as WorkspaceImportReceipt
from modules.workspace_compat.domain.receipts import WorkspaceFileEntry as WorkspaceFileEntry
from modules.workspace_compat.legacy_store import WorkspaceFileStore as WorkspaceFileStore
from project_runtime_client.analysis.domain.workspace import (
    WorkspaceFileMetadata as WorkspaceFileMetadata,
)
from project_runtime_client.analysis.infrastructure.workspace_transfers import (
    AnalysisTransferError as AnalysisTransferError,
)
from project_runtime_client.analysis.infrastructure.workspace_transfers import (
    _CompositionAnalysisWorkspaceTransfers as _SharedAnalysisWorkspaceTransfers,
)
from project_runtime_client.analysis.infrastructure.workspace_transfers import (
    _OwnerWorkspaceAdapter as _SharedOwnerWorkspaceAdapter,
)
from service_runtime.mcp_http import mcp_http_client as mcp_http_client

from .artifact_client import call_artifact as call_artifact
from .artifact_commands import ArchiveProject as ArchiveProject
from .artifact_commands import ArtifactCommand as ArtifactCommand
from .artifact_commands import BeginArtifact as BeginArtifact
from .artifact_commands import CancelArtifact as CancelArtifact
from .artifact_commands import DeleteArtifact as DeleteArtifact
from .artifact_commands import ExportProgram as ExportProgram
from .artifact_commands import FinishArtifact as FinishArtifact
from .artifact_commands import ImportBinary as ImportBinary
from .artifact_commands import ImportProgram as ImportProgram
from .artifact_commands import ReadArtifact as ReadArtifact
from .artifact_commands import RestoreProject as RestoreProject
from .artifact_commands import WriteArtifact as WriteArtifact
from .artifact_replies import ArtifactChunk as ArtifactChunk
from .artifact_replies import ArtifactExportPath as ArtifactExportPath
from .artifact_replies import DirectArtifactReceipt as DirectArtifactReceipt
from .artifact_replies import ImportedBinaryReply as ImportedBinaryReply
from .artifact_replies import ImportedProgramReply as ImportedProgramReply
from .artifact_replies import RestoredProjectReply as RestoredProjectReply
from .artifact_replies import StageFinished as StageFinished
from .artifact_replies import StageOpened as StageOpened
from .artifact_replies import StageWritten as StageWritten
from .artifact_replies import TransferAcknowledgement as TransferAcknowledgement


class _OwnerWorkspaceAdapter(_SharedOwnerWorkspaceAdapter):
    """Keep this composition root's workspace adapter type."""


class AnalysisWorkspaceTransfers(
    _SharedAnalysisWorkspaceTransfers[AnalysisSettings, WorkspaceFileStore]
):
    """Bind local workspace custody to the unchanged transfer backend."""

    _workspace_adapter_type = _OwnerWorkspaceAdapter
