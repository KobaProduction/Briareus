"""Execute the original Files closures against a descriptor-confined workspace."""
from __future__ import annotations

from pydantic import ConfigDict, validate_call

from common.runtime_annotations import DESTRUCTIVE_LOCAL, READ_ONLY_LOCAL, WRITE_LOCAL
from modules.files.file_tools import register_file_tools

from .node_workspace import MAX_BYTES


READ_TOOLS = frozenset({"file_status", "file_list", "file_info", "file_read", "file_hash"})
WRITE_TOOLS = frozenset({"file_write_text", "file_write", "file_ingest", "file_mkdir", "file_copy", "file_move", "file_delete"})


def register_original_tools(mcp, workspace):
    register_file_tools(mcp, READ_ONLY_LOCAL, WRITE_LOCAL, DESTRUCTIVE_LOCAL,
        workspace=workspace, max_file_bytes=MAX_BYTES, ingest_file=workspace.ingest)


class FileDispatch:
    def __init__(self, workspace):
        self.tools = {}
        register_original_tools(self, workspace)
        if set(self.tools) != READ_TOOLS | WRITE_TOOLS:
            raise ValueError("Original Files catalogue changed")

    def tool(self, **_metadata):
        def register(function):
            if function.__name__ in self.tools:
                raise ValueError("Duplicate Files source tool")
            self.tools[function.__name__] = validate_call(config=ConfigDict(strict=True), validate_return=True)(function)
            return function
        return register

    def call(self, name, arguments):
        return self.tools[name](**arguments)
