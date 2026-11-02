"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

from dataclasses import dataclass as dataclass
from typing import Protocol as Protocol

from modules.workspace_compat.domain.receipts import WorkspaceWrite as WorkspaceWrite
from modules.workspace_compat.domain.transfers import WorkspaceAppendPlan as WorkspaceAppendPlan
from project_runtime_client.workspace_compat.application.transfers import (
    WorkspaceChunkCommand as WorkspaceChunkCommand,
)
from project_runtime_client.workspace_compat.application.transfers import (
    WorkspaceChunkStorage as WorkspaceChunkStorage,
)
from project_runtime_client.workspace_compat.application.transfers import (
    WorkspaceChunkTarget as WorkspaceChunkTarget,
)
from project_runtime_client.workspace_compat.application.transfers import (
    _BoundAppendWorkspaceChunk as _SharedAppendWorkspaceChunk,
)


class AppendWorkspaceChunk(_SharedAppendWorkspaceChunk):
    _plan_factory = WorkspaceAppendPlan
