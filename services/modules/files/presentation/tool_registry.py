"""Decorator contract retaining each original validated tool signature."""

from collections.abc import Callable
from typing import Protocol

from fastmcp import FastMCP as FastMCP
from fastmcp.utilities.types import NotSet as NotSet
from fastmcp.utilities.types import NotSetT as NotSetT
from files_hand.presentation.tool_registry import McpFilesToolRegistry as _McpFilesToolRegistry
from mcp.types import CallToolResult, ToolAnnotations
from pydantic.json_schema import JsonSchemaValue


class FileToolDecorator(Protocol):
    def __call__[**Parameters, Result: CallToolResult](
        self,
        function: Callable[Parameters, Result],
    ) -> Callable[Parameters, Result]: ...


class FilesToolRegistry(Protocol):
    def tool(
        self,
        *,
        title: str,
        annotations: ToolAnnotations,
        file_parameters: tuple[str, ...] = (),
        output_schema: JsonSchemaValue | None = None,
    ) -> FileToolDecorator: ...


class McpFilesToolRegistry[State](_McpFilesToolRegistry[State]):
    """Nominal legacy Files registry over its owner's canonical metadata adapter."""
