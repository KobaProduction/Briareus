"""Keep dynamic MCP schemas and result documents at the final SDK boundary."""

import json

from fastmcp.client.client import CallToolResult as ClientCallToolResult
from fastmcp.tools import ToolResult
from mcp.types import CallToolResult, TextContent, Tool

from bridge.application.backend_routing import BackendLocation
from bridge.domain.backend_failure import BackendFailure, tool_failure

from .backend_models import BackendCallFailure


def catalog_reply(
    location: BackendLocation,
    tools: tuple[Tool, ...],
    *,
    error_type: str | None = None,
) -> CallToolResult:
    # These are the existing legacy discovery fields, not the MCP Tool aliases.
    entries = []
    for tool in tools:
        entry = {
            "name": tool.name,
            "description": tool.description or "",
            "input_schema": tool.input_schema,
        }
        if tool.title:
            entry["title"] = tool.title
        if tool.output_schema is not None:
            entry["output_schema"] = tool.output_schema
        entries.append(entry)
    fields: dict[str, object] = {
        "backend": location.name,
        "public_path": location.public_path,
        "status": "available" if error_type is None else "not_available",
        "tools": entries,
    }
    if error_type is None:
        fields["count"] = len(tools)
    else:
        fields["error_type"] = error_type
    converted = ToolResult(content=fields, structured_content=fields)
    return CallToolResult(
        content=converted.content, structured_content=converted.structured_content
    )


def failure_reply(backend: str, tool: str, failure: BackendFailure) -> CallToolResult:
    view = BackendCallFailure(
        backend=backend,
        tool=tool,
        error_type=failure.error_type,
        message=failure.message,
        hint=failure.hint,
    )
    fields = view.model_dump(mode="json")
    converted = ToolResult(content=fields, structured_content=fields)
    return CallToolResult(
        content=converted.content, structured_content=converted.structured_content
    )


def call_reply(backend: str, tool: str, result: ClientCallToolResult) -> CallToolResult:
    if result.is_error:
        return failure_reply(backend, tool, tool_failure())
    value: object = result.structured_content
    if value is None:
        value = result.data
    if value is None:
        value = [block.text for block in result.content if isinstance(block, TextContent)] or None
    try:
        json.dumps(value, allow_nan=False)
    except (TypeError, ValueError):
        raise ValueError("Backend tool result is not valid JSON-compatible data") from None
    fields = {"backend": backend, "tool": tool, "status": "ok", "result": value}
    converted = ToolResult(content=fields, structured_content=fields)
    return CallToolResult(
        content=converted.content, structured_content=converted.structured_content
    )
