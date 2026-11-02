"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

from dataclasses import dataclass as dataclass
from typing import Literal as Literal

from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceAbsent as WorkspaceAbsent,
)
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceDelete as WorkspaceDelete,
)
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceDeleted as WorkspaceDeleted,
)
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceDirectoryEntry as WorkspaceDirectoryEntry,
)
from project_runtime_client.workspace_compat.domain.receipts import WorkspaceEntry as WorkspaceEntry
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceFileEntry as WorkspaceFileEntry,
)
from project_runtime_client.workspace_compat.domain.receipts import WorkspacePage as WorkspacePage
from project_runtime_client.workspace_compat.domain.receipts import WorkspaceRead as WorkspaceRead
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceStatus as WorkspaceStatus,
)
from project_runtime_client.workspace_compat.domain.receipts import WorkspaceWrite as WorkspaceWrite
