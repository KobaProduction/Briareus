"""Execute the original Files closures against a descriptor-confined workspace."""

from __future__ import annotations

from collections.abc import Callable

from mcp.types import CallToolRequestParams, CallToolResult, ToolAnnotations
from pydantic.json_schema import JsonSchemaValue

from common.runtime_annotations import DESTRUCTIVE_LOCAL, READ_ONLY_LOCAL, WRITE_LOCAL
from files_hand.presentation.tool_registry import FilesToolRegistry, FileToolDecorator
from hand_runtime.tool_binding import ValidatedInvocation, bind_invocation
from modules.files.file_tools import register_file_tools

from .node_workspace import MAX_BYTES, NodeWorkspace

READ_TOOLS = frozenset({"file_status", "file_list", "file_info", "file_read", "file_hash"})
WRITE_TOOLS = frozenset(
    {
        "file_write_text",
        "file_write",
        "file_ingest",
        "file_mkdir",
        "file_copy",
        "file_move",
        "file_delete",
    }
)


def register_original_tools(mcp: FilesToolRegistry, workspace: NodeWorkspace) -> None:
    register_file_tools(
        mcp,
        READ_ONLY_LOCAL,
        WRITE_LOCAL,
        DESTRUCTIVE_LOCAL,
        workspace=workspace,
        max_file_bytes=MAX_BYTES,
        ingest_file=workspace.ingest,
    )


class FileDispatch:
    def __init__(self, workspace: NodeWorkspace) -> None:
        self.tools: dict[str, ValidatedInvocation[CallToolResult]] = {}
        register_original_tools(self, workspace)
        if set(self.tools) != READ_TOOLS | WRITE_TOOLS:
            raise ValueError("Original Files catalogue changed")

    def tool(
        self,
        *,
        title: str,
        annotations: ToolAnnotations,
        file_parameters: tuple[str, ...] = (),
        output_schema: JsonSchemaValue | None = None,
    ) -> FileToolDecorator:
        del title, annotations, file_parameters, output_schema

        def register[**Parameters, Result: CallToolResult](
            function: Callable[Parameters, Result],
        ) -> Callable[Parameters, Result]:
            if function.__name__ in self.tools:
                raise ValueError("Duplicate Files source tool")
            self.tools[function.__name__] = bind_invocation(function)
            return function

        return register

    def call(self, call: CallToolRequestParams) -> CallToolResult:
        return self.tools[call.name](call)
