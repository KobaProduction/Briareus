"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

from dataclasses import dataclass as dataclass

from project_runtime_client.workspace_compat.domain.transfers import (
    EarlyOffsetWorkspaceAppendPlan as _EarlyOffsetWorkspaceAppendPlan,
)
from project_runtime_client.workspace_compat.domain.transfers import (
    WorkspaceFileError as WorkspaceFileError,
)
from project_runtime_client.workspace_compat.domain.transfers import (
    WorkspaceListWindow as WorkspaceListWindow,
)
from project_runtime_client.workspace_compat.domain.transfers import (
    WorkspaceReadWindow as WorkspaceReadWindow,
)
from project_runtime_client.workspace_compat.domain.transfers import (
    require_offset as require_offset,
)

WorkspaceAppendPlan = _EarlyOffsetWorkspaceAppendPlan
