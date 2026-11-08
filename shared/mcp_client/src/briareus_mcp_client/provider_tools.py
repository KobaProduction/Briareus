"""Forward external MCP contracts without converting their payloads into application state."""

from collections.abc import Awaitable, Callable

from briareus_json_values import JsonObject, JsonValue, json_object
from fastmcp.client.client import CallToolResult
from fastmcp.tools import FunctionTool, ToolResult
from mcp.types import Tool

ToolCaller = Callable[[str, JsonObject], Awaitable[CallToolResult]]


def forwarded_tool(tool: Tool, caller: ToolCaller, *, project_scoped: bool = False) -> FunctionTool:
    schema = json_object(tool.input_schema, context="external MCP input schema")
    if project_scoped:
        properties = schema.get("properties", {})
        if not isinstance(properties, dict) or "project_id" in properties:
            raise ValueError("Backend tool conflicts with project routing")
        required = schema.get("required", [])
        if not isinstance(required, list):
            raise ValueError("Backend tool has an invalid required-field schema")
        schema = {
            **schema,
            "properties": {
                **properties,
                "project_id": {
                    "type": "string",
                    "pattern": "^[a-z][a-z0-9_-]{0,62}$",
                    "description": "Registered Server project for this operation.",
                },
            },
            "required": [*required, "project_id"],
        }

    async def invoke(**arguments: JsonValue) -> ToolResult:
        result = await caller(tool.name, arguments)
        return ToolResult(
            content=result.content,
            structured_content=result.structured_content,
            is_error=result.is_error,
        )

    return FunctionTool(
        name=tool.name,
        description=tool.description,
        parameters=schema,
        annotations=tool.annotations,
        fn=invoke,
    )
