"""Concrete import receipts and native documents meet only at the MCP edge."""

import json

from mcp.types import CallToolResult, TextContent
from pydantic import TypeAdapter

from .application.imports import ImportResult
from .domain.commands import NativeCommand

_IMPORT_RESULT: TypeAdapter[ImportResult] = TypeAdapter(ImportResult)


def analyzer_result(result: ImportResult | CallToolResult) -> CallToolResult:
    if isinstance(result, CallToolResult):
        return result
    payload = _IMPORT_RESULT.dump_python(result, mode="json")
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, allow_nan=False))],
        structured_content=payload,
        is_error=False,
    )


def native_result(command: NativeCommand, raw: bytes) -> CallToolResult:
    # radare2 owns these records. Decode and paginate them only at this
    # terminal process-to-MCP adapter, never as a first-party domain entity.
    value: object = json.loads(raw)
    fields: dict[str, object] = {"binary_id": str(command.binary_id)}
    if command.page is None:
        fields["result"] = value
    else:
        if not isinstance(value, list):
            raise ValueError("Unexpected native analysis collection")
        offset, limit = command.page
        fields.update(total=len(value), offset=offset, items=value[offset : offset + limit])
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(fields, allow_nan=False))],
        structured_content=fields,
        is_error=False,
    )
