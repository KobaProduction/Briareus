"""Typed existing workspace operations consumed by the Files MCP boundary."""

from typing import Protocol

from modules.files.receipts import WorkspaceHash, WorkspaceIngestReceipt
from modules.workspace_compat.domain.receipts import (
    WorkspaceDelete,
    WorkspacePage,
    WorkspaceRead,
    WorkspaceStatus,
    WorkspaceWrite,
)

from .workspace_receipts import FileDirectoryPage, FileEntry, NodeIngestReceipt
from .write_chunk import ChunkWriteReceipt

type IngestReceipt = WorkspaceIngestReceipt | NodeIngestReceipt
type FileToolReceipt = (
    WorkspaceStatus
    | FileDirectoryPage
    | FileEntry
    | WorkspaceRead
    | WorkspaceHash
    | ChunkWriteReceipt
    | IngestReceipt
    | WorkspaceDelete
)


class FilesWorkspace[EntryT: FileEntry = FileEntry](Protocol):
    def status(self) -> WorkspaceStatus: ...
    def list(
        self, path: str = "", *, offset: int = 0, limit: int = 200
    ) -> WorkspacePage | FileDirectoryPage: ...
    def info(self, path: str) -> EntryT: ...
    def read(self, path: str, *, offset: int = 0, length: int = 1024 * 1024) -> WorkspaceRead: ...
    def sha256(self, path: str) -> str: ...
    def write_text(
        self, path: str, content: str, *, overwrite: bool = True, create_parents: bool = True
    ) -> EntryT: ...
    def write_chunk(
        self,
        path: str,
        data_base64: str,
        *,
        offset: int = 0,
        truncate: bool = False,
        create_parents: bool = True,
        max_file_bytes: int,
    ) -> WorkspaceWrite | ChunkWriteReceipt: ...
    def mkdir(self, path: str, *, parents: bool = True) -> EntryT: ...
    def copy(self, source: str, destination: str, *, overwrite: bool = False) -> EntryT: ...
    def move(self, source: str, destination: str, *, overwrite: bool = False) -> EntryT: ...
    def delete(self, path: str, *, recursive: bool = False) -> WorkspaceDelete: ...
