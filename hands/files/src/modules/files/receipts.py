"""Compatibility API for the canonical typed workspace/attachment client."""

from __future__ import annotations

from dataclasses import dataclass as dataclass
from typing import Literal as Literal

from modules.workspace_compat.domain.receipts import WorkspaceFileEntry as WorkspaceFileEntry
from project_runtime_client.files.domain.receipts import WorkspaceHash as WorkspaceHash
from project_runtime_client.files.domain.receipts import (
    WorkspaceIngestReceipt as WorkspaceIngestReceipt,
)
