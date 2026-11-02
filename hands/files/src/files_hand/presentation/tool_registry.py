"""Decorator contract retaining each original validated tool signature."""

from collections.abc import Callable
from typing import Protocol

from fastmcp import FastMCP
from fastmcp.utilities.types import NotSet, NotSetT
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


class McpFilesToolRegistry[State]:
    """Keep the SDK metadata adapter inside each independently packaged owner."""

    def __init__(self, mcp: FastMCP[State]) -> None:
        self._mcp = mcp

    def tool(
        self,
        *,
        title: str,
        annotations: ToolAnnotations,
        output_schema: JsonSchemaValue | NotSetT | None = NotSet,
        file_parameters: tuple[str, ...] = (),
    ) -> FileToolDecorator:
        def register[**P, Result: CallToolResult](
            function: Callable[P, Result],
        ) -> Callable[P, Result]:
            return self._mcp.tool(
                function,
                title=title,
                annotations=annotations,
                output_schema=output_schema,
                meta={"openai/fileParams": list(file_parameters)} if file_parameters else None,
            )

        return register
