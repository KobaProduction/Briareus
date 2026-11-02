from __future__ import annotations

from typing import Protocol

from fastmcp.utilities.json_schema import compress_schema
from files_hand.application.workspace_ports import FilesWorkspace, IngestReceipt
from files_hand.application.workspace_receipts import FileDirectoryPage, FileEntry
from files_hand.application.write_chunk import ChunkWriteReceipt
from files_hand.presentation.file_registration import _FileTools
from files_hand.presentation.results import file_result
from files_hand.presentation.tool_registry import FilesToolRegistry
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import TypeAdapter

from modules.workspace_compat.domain.receipts import (
    WorkspaceDelete,
    WorkspacePage,
    WorkspaceRead,
    WorkspaceStatus,
)

from .models import ClientFile
from .receipts import WorkspaceHash
from .workspace_ingress import ingest_workspace_file
from .workspace_store import WorkspaceFileStore

FILE_STATUS_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[WorkspaceStatus](WorkspaceStatus).json_schema(mode="serialization"),
    },
    prune_titles=True,
)

FILE_LIST_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[FileDirectoryPage](FileDirectoryPage).json_schema(mode="serialization"),
    },
    prune_titles=True,
)

FILE_ENTRY_SCHEMA = compress_schema(
    {"type": "object", **TypeAdapter[FileEntry](FileEntry).json_schema(mode="serialization")},
    prune_titles=True,
)

FILE_READ_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[WorkspaceRead](WorkspaceRead).json_schema(mode="serialization"),
    },
    prune_titles=True,
)

FILE_HASH_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[WorkspaceHash](WorkspaceHash).json_schema(mode="serialization"),
    },
    prune_titles=True,
)

FILE_WRITE_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[ChunkWriteReceipt](ChunkWriteReceipt).json_schema(mode="serialization"),
    },
    prune_titles=True,
)

FILE_INGEST_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[IngestReceipt](IngestReceipt).json_schema(mode="serialization"),
    },
    prune_titles=True,
)

FILE_DELETE_SCHEMA = compress_schema(
    {
        "type": "object",
        **TypeAdapter[WorkspaceDelete](WorkspaceDelete).json_schema(mode="serialization"),
    },
    prune_titles=True,
)


class AttachmentIngest(Protocol):
    def __call__(
        self,
        *,
        file: ClientFile,
        destination: str,
        expected_size: int | None = None,
        expected_sha256: str = "",
        overwrite: bool = False,
    ) -> IngestReceipt: ...


def directory_page(page: WorkspacePage | FileDirectoryPage) -> FileDirectoryPage:
    if isinstance(page, FileDirectoryPage):
        return page
    return FileDirectoryPage(
        page.path, page.entries, page.count, page.total, page.offset, page.limit, page.truncated
    )


def register_file_tools(
    mcp: FilesToolRegistry,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    *,
    workspace: FilesWorkspace,
    max_file_bytes: int,
    ingest_file: AttachmentIngest | None = None,
) -> None:

    tools = _FileTools(workspace, file_result)

    mcp.tool(title="File status", annotations=read_annotations, output_schema=FILE_STATUS_SCHEMA)(
        tools.file_status
    )

    @mcp.tool(title="File list", annotations=read_annotations, output_schema=FILE_LIST_SCHEMA)
    def file_list(path: str = "", offset: int = 0, limit: int = 200) -> CallToolResult:
        return file_result(directory_page(workspace.list(path, offset=offset, limit=limit)))

    mcp.tool(title="File info", annotations=read_annotations, output_schema=FILE_ENTRY_SCHEMA)(
        tools.file_info
    )

    mcp.tool(title="File read", annotations=read_annotations, output_schema=FILE_READ_SCHEMA)(
        tools.file_read
    )

    mcp.tool(title="File hash", annotations=read_annotations, output_schema=FILE_HASH_SCHEMA)(
        tools.file_hash
    )

    mcp.tool(
        title="File write text", annotations=write_annotations, output_schema=FILE_ENTRY_SCHEMA
    )(tools.file_write_text)

    @mcp.tool(
        title="File write chunk", annotations=write_annotations, output_schema=FILE_WRITE_SCHEMA
    )
    def file_write(
        path: str,
        data_base64: str,
        offset: int = 0,
        truncate: bool = False,
        create_parents: bool = True,
    ) -> CallToolResult:
        result = workspace.write_chunk(
            path,
            data_base64,
            offset=offset,
            truncate=truncate,
            create_parents=create_parents,
            max_file_bytes=max_file_bytes,
        )
        return file_result(
            ChunkWriteReceipt(
                result.path, result.bytes_written, result.next_offset, result.size_bytes
            )
        )

    @mcp.tool(
        title="File ingest attachment",
        annotations=write_annotations,
        file_parameters=("file",),
        output_schema=FILE_INGEST_SCHEMA,
    )
    def file_ingest(
        file: ClientFile,
        destination: str,
        expected_size: int | None = None,
        expected_sha256: str = "",
        overwrite: bool = False,
    ) -> CallToolResult:
        if ingest_file is not None:
            return file_result(
                ingest_file(
                    file=file,
                    destination=destination,
                    expected_size=expected_size,
                    expected_sha256=expected_sha256,
                    overwrite=overwrite,
                )
            )
        if not isinstance(workspace, WorkspaceFileStore):
            raise ValueError("Configured attachment ingest adapter required")
        return file_result(
            ingest_workspace_file(
                file=file,
                destination=destination,
                expected_size=expected_size,
                expected_sha256=expected_sha256,
                overwrite=overwrite,
                workspace=workspace,
                max_bytes=max_file_bytes,
            )
        )

    mcp.tool(title="File mkdir", annotations=write_annotations, output_schema=FILE_ENTRY_SCHEMA)(
        tools.file_mkdir
    )

    mcp.tool(title="File copy", annotations=write_annotations, output_schema=FILE_ENTRY_SCHEMA)(
        tools.file_copy
    )

    mcp.tool(title="File move", annotations=write_annotations, output_schema=FILE_ENTRY_SCHEMA)(
        tools.file_move
    )

    mcp.tool(
        title="File delete", annotations=destructive_annotations, output_schema=FILE_DELETE_SCHEMA
    )(tools.file_delete)
