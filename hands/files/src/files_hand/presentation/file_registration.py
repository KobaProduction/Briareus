"""Original Files SDK methods bound to each root's exact workspace and formatter."""

from __future__ import annotations

from collections.abc import Callable

from mcp.types import CallToolResult

from files_hand.application.workspace_ports import FilesWorkspace
from files_hand.application.workspace_receipts import FileEntry
from project_runtime_client.files.domain.receipts import WorkspaceHash
from project_runtime_client.workspace_compat.domain.receipts import (
    WorkspaceDelete,
    WorkspaceRead,
    WorkspaceStatus,
)

type _CommonFileReceipt[EntryT: FileEntry] = (
    WorkspaceStatus | EntryT | WorkspaceRead | WorkspaceHash | WorkspaceDelete
)


class _FileTools[EntryT: FileEntry]:
    def __init__(
        self,
        workspace: FilesWorkspace[EntryT],
        file_result: Callable[[_CommonFileReceipt[EntryT]], CallToolResult],
    ) -> None:
        self.workspace = workspace
        self.file_result = file_result

    def file_status(self) -> CallToolResult:
        return self.file_result(self.workspace.status())

    def file_info(self, path: str) -> CallToolResult:
        return self.file_result(self.workspace.info(path))

    def file_read(self, path: str, offset: int = 0, length: int = 1024 * 1024) -> CallToolResult:
        return self.file_result(self.workspace.read(path, offset=offset, length=length))

    def file_hash(self, path: str) -> CallToolResult:
        return self.file_result(
            WorkspaceHash(path.strip().lstrip("/"), self.workspace.sha256(path))
        )

    def file_write_text(
        self, path: str, content: str, overwrite: bool = True, create_parents: bool = True
    ) -> CallToolResult:
        return self.file_result(
            self.workspace.write_text(
                path, content, overwrite=overwrite, create_parents=create_parents
            )
        )

    def file_mkdir(self, path: str, parents: bool = True) -> CallToolResult:
        return self.file_result(self.workspace.mkdir(path, parents=parents))

    def file_copy(self, source: str, destination: str, overwrite: bool = False) -> CallToolResult:
        return self.file_result(self.workspace.copy(source, destination, overwrite=overwrite))

    def file_move(self, source: str, destination: str, overwrite: bool = False) -> CallToolResult:
        return self.file_result(self.workspace.move(source, destination, overwrite=overwrite))

    def file_delete(self, path: str, recursive: bool = False) -> CallToolResult:
        return self.file_result(self.workspace.delete(path, recursive=recursive))
