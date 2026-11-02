"""Keep the legacy flat structuredContent envelope at the SDK boundary."""

import json

from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter

from modules.files.receipts import WorkspaceHash, WorkspaceIngestReceipt
from modules.workspace_compat.domain.receipts import (
    WorkspaceDelete,
    WorkspaceEntry,
    WorkspacePage,
    WorkspaceRead,
    WorkspaceStatus,
    WorkspaceWrite,
)

type FilesReceipt = (
    WorkspaceStatus
    | WorkspacePage
    | WorkspaceEntry
    | WorkspaceRead
    | WorkspaceWrite
    | WorkspaceDelete
    | WorkspaceHash
    | WorkspaceIngestReceipt
)


def file_result(result: FilesReceipt) -> CallToolResult:
    payload = TypeAdapter[FilesReceipt](FilesReceipt).dump_python(result, mode="json")
    if not isinstance(payload, dict):
        raise ValueError("Files receipt must be a JSON object")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, allow_nan=False))],
        structured_content=payload,
        is_error=False,
    )
