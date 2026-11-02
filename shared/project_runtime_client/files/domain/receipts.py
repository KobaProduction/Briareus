"""Typed Files tool receipts over the shared workspace contract."""

from dataclasses import dataclass
from typing import Literal

from project_runtime_client.workspace_compat.domain.receipts import WorkspaceFileEntry


@dataclass(frozen=True, slots=True)
class WorkspaceHash:
    path: str
    sha256: str


@dataclass(frozen=True, slots=True, kw_only=True)
class WorkspaceIngestReceipt(WorkspaceFileEntry):
    sha256: str
    completed: Literal[True] = True
    transport: Literal["client-file"] = "client-file"
