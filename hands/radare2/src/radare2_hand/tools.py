"""Typed static analyzer catalogue, reused by metadata and actual dispatch."""
from typing import Annotated

from pydantic import Field


def register_tools(mcp, execute=None):
    async def call(name, values):
        if execute is None:
            raise RuntimeError("Metadata registration cannot execute tools")
        return await execute(name, {key: value for key, value in values.items() if key != "call"})

    @mcp.tool()
    async def radare2_import_start(name: str, sha256: str, size: Annotated[int, Field(ge=1, le=16777216)]):
        """Begin a private binary upload; declare its exact SHA256 and byte length."""
        return await call("radare2_import_start", locals())

    @mcp.tool()
    async def radare2_import_chunk(upload_id: str, offset: Annotated[int, Field(ge=0)], content_base64: str):
        """Append up to 12288 bytes of base64 data at the exact acknowledged offset."""
        return await call("radare2_import_chunk", locals())

    @mcp.tool()
    async def radare2_import_finish(upload_id: str):
        """Verify the complete upload digest and commit an immutable analysis binary."""
        return await call("radare2_import_finish", locals())

    @mcp.tool()
    async def radare2_import_abort(upload_id: str):
        """Discard an unfinished upload and release its reserved storage capacity."""
        return await call("radare2_import_abort", locals())

    @mcp.tool()
    async def radare2_list_binaries():
        """List binaries in this project's private radare2 storage."""
        return await call("radare2_list_binaries", {})

    @mcp.tool()
    async def radare2_delete_binary(binary_id: str):
        """Permanently delete one imported binary and its metadata."""
        return await call("radare2_delete_binary", locals())

    @mcp.tool()
    async def radare2_binary_info(binary_id: str):
        """Inspect actual binary format, architecture, bits, sections and metadata."""
        return await call("radare2_binary_info", locals())

    @mcp.tool()
    async def radare2_functions(binary_id: str, offset: Annotated[int, Field(ge=0)] = 0,
                               limit: Annotated[int, Field(ge=1, le=500)] = 100):
        """Run bounded native function analysis and return a page of discovered functions."""
        return await call("radare2_functions", locals())

    @mcp.tool()
    async def radare2_strings(binary_id: str, offset: Annotated[int, Field(ge=0)] = 0,
                             limit: Annotated[int, Field(ge=1, le=500)] = 100):
        """Inspect a page of native binary strings and their addresses."""
        return await call("radare2_strings", locals())

    @mcp.tool()
    async def radare2_disassemble(binary_id: str, address: str = "0x0",
                                 count: Annotated[int, Field(ge=1, le=256)] = 32):
        """Disassemble a bounded number of instructions at a hexadecimal address."""
        return await call("radare2_disassemble", locals())

    @mcp.tool()
    async def radare2_xrefs(binary_id: str, address: str):
        """Analyze native cross references to a hexadecimal address."""
        return await call("radare2_xrefs", locals())
