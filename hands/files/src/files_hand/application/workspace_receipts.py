"""Node workspace receipts preserve the descriptor API's absent MIME field."""

from dataclasses import dataclass
from typing import Literal

from modules.workspace_compat.domain.receipts import WorkspaceDirectoryEntry, WorkspaceFileEntry


@dataclass(frozen=True, slots=True)
class NodeFileEntry:
    path: str
    name: str
    size_bytes: int
    modified_at_ns: int
    type: Literal["file"] = "file"


type FileEntry = NodeFileEntry | WorkspaceFileEntry | WorkspaceDirectoryEntry


@dataclass(frozen=True, slots=True)
class FileDirectoryPage:
    path: str
    entries: tuple[FileEntry, ...]
    count: int
    total: int
    offset: int
    limit: int
    truncated: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class NodeIngestReceipt(NodeFileEntry):
    sha256: str
    completed: Literal[True] = True
    transport: Literal["client-file"] = "client-file"
