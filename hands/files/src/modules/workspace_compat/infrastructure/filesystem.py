"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

import base64 as base64
import hashlib as hashlib
import mimetypes as mimetypes
import os as os
import shutil as shutil
import uuid as uuid
from dataclasses import dataclass as dataclass
from pathlib import Path as Path
from typing import BinaryIO as BinaryIO

from modules.workspace_compat.application.transfers import (
    AppendWorkspaceChunk as AppendWorkspaceChunk,
)
from modules.workspace_compat.application.transfers import (
    WorkspaceChunkCommand as WorkspaceChunkCommand,
)
from modules.workspace_compat.application.transfers import (
    WorkspaceChunkTarget as WorkspaceChunkTarget,
)
from modules.workspace_compat.domain.receipts import WorkspaceAbsent as WorkspaceAbsent
from modules.workspace_compat.domain.receipts import WorkspaceDelete as WorkspaceDelete
from modules.workspace_compat.domain.receipts import WorkspaceDeleted as WorkspaceDeleted
from modules.workspace_compat.domain.receipts import (
    WorkspaceDirectoryEntry as WorkspaceDirectoryEntry,
)
from modules.workspace_compat.domain.receipts import WorkspaceEntry as WorkspaceEntry
from modules.workspace_compat.domain.receipts import WorkspaceFileEntry as WorkspaceFileEntry
from modules.workspace_compat.domain.receipts import WorkspacePage as WorkspacePage
from modules.workspace_compat.domain.receipts import WorkspaceRead as WorkspaceRead
from modules.workspace_compat.domain.receipts import WorkspaceStatus as WorkspaceStatus
from modules.workspace_compat.domain.receipts import WorkspaceWrite as WorkspaceWrite
from modules.workspace_compat.domain.transfers import WorkspaceAppendPlan
from modules.workspace_compat.domain.transfers import WorkspaceFileError as WorkspaceFileError
from modules.workspace_compat.domain.transfers import WorkspaceListWindow as WorkspaceListWindow
from modules.workspace_compat.domain.transfers import WorkspaceReadWindow as WorkspaceReadWindow
from modules.workspace_compat.domain.transfers import require_offset as require_offset
from project_runtime_client.workspace_compat.infrastructure.filesystem import (
    WorkspaceFileStore as _SharedWorkspaceFileStore,
)
from project_runtime_client.workspace_compat.infrastructure.filesystem import (
    _PathChunkTarget as _PathChunkTarget,
)


class WorkspaceFileStore(_SharedWorkspaceFileStore):
    _append_plan = WorkspaceAppendPlan
