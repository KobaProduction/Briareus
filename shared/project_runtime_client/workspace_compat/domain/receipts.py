"""Immutable file transfer results; serialization belongs to outer adapters."""

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True, slots=True)
class WorkspaceStatus:
    root: str
    free_bytes: int
    used_bytes: int
    total_bytes: int


@dataclass(frozen=True, slots=True)
class WorkspaceFileEntry:
    path: str
    name: str
    size_bytes: int
    modified_at_ns: int
    mime_type: str
    type: Literal["file"] = "file"


@dataclass(frozen=True, slots=True)
class WorkspaceDirectoryEntry:
    path: str
    name: str
    size_bytes: int
    modified_at_ns: int
    type: Literal["directory"] = "directory"


WorkspaceEntry = WorkspaceFileEntry | WorkspaceDirectoryEntry


@dataclass(frozen=True, slots=True)
class WorkspacePage:
    path: str
    entries: tuple[WorkspaceEntry, ...]
    count: int
    total: int
    offset: int
    limit: int
    truncated: bool


@dataclass(frozen=True, slots=True)
class WorkspaceRead:
    path: str
    offset: int
    bytes_read: int
    next_offset: int
    size_bytes: int
    eof: bool
    data_base64: str


@dataclass(frozen=True, slots=True)
class WorkspaceWrite:
    path: str
    bytes_written: int
    next_offset: int
    size_bytes: int


@dataclass(frozen=True, slots=True)
class WorkspaceDeleted:
    path: str
    deleted: Literal[True] = True


@dataclass(frozen=True, slots=True)
class WorkspaceAbsent:
    path: str
    already_absent: Literal[True] = True


WorkspaceDelete = WorkspaceDeleted | WorkspaceAbsent
