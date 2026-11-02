"""Typed static analyzer catalogue, reused by metadata and actual dispatch."""

from collections.abc import Awaitable, Callable
from typing import Annotated

from fastmcp import FastMCP
from mcp.types import CallToolResult
from pydantic import Field

from .domain.binaries import identifier
from .domain.commands import (
    AbortUpload,
    AnalyzerCommand,
    DeleteBinary,
    FinishUpload,
    ListBinaries,
    StartUpload,
    UploadChunk,
    native_command,
)
from .presentation import analyzer_result
from .runtime import AnalyzerResult


def register_tools(
    mcp: FastMCP[None],
    execute: Callable[[AnalyzerCommand], Awaitable[AnalyzerResult]] | None = None,
) -> None:
    async def call(command: AnalyzerCommand) -> CallToolResult:
        if execute is None:
            raise RuntimeError("Metadata registration cannot execute tools")
        return analyzer_result(await execute(command))

    @mcp.tool()
    async def radare2_import_start(
        name: str, sha256: str, size: Annotated[int, Field(ge=1, le=16777216)]
    ) -> CallToolResult:
        """Begin a private binary upload; declare its exact SHA256 and byte length."""
        return await call(StartUpload(name, sha256, size))

    @mcp.tool()
    async def radare2_import_chunk(
        upload_id: str, offset: Annotated[int, Field(ge=0)], content_base64: str
    ) -> CallToolResult:
        """Append up to 12288 bytes of base64 data at the exact acknowledged offset."""
        return await call(UploadChunk(identifier(upload_id), offset, content_base64))

    @mcp.tool()
    async def radare2_import_finish(upload_id: str) -> CallToolResult:
        """Verify the complete upload digest and commit an immutable analysis binary."""
        return await call(FinishUpload(identifier(upload_id)))

    @mcp.tool()
    async def radare2_import_abort(upload_id: str) -> CallToolResult:
        """Discard an unfinished upload and release its reserved storage capacity."""
        return await call(AbortUpload(identifier(upload_id)))

    @mcp.tool()
    async def radare2_list_binaries() -> CallToolResult:
        """List binaries in this project's private radare2 storage."""
        return await call(ListBinaries())

    @mcp.tool()
    async def radare2_delete_binary(binary_id: str) -> CallToolResult:
        """Permanently delete one imported binary and its metadata."""
        return await call(DeleteBinary(identifier(binary_id)))

    @mcp.tool()
    async def radare2_binary_info(binary_id: str) -> CallToolResult:
        """Inspect actual binary format, architecture, bits, sections and metadata."""
        return await call(native_command("radare2_binary_info", identifier(binary_id)))

    @mcp.tool()
    async def radare2_functions(
        binary_id: str,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> CallToolResult:
        """Run bounded native function analysis and return a page of discovered functions."""
        return await call(
            native_command("radare2_functions", identifier(binary_id), offset=offset, limit=limit)
        )

    @mcp.tool()
    async def radare2_strings(
        binary_id: str,
        offset: Annotated[int, Field(ge=0)] = 0,
        limit: Annotated[int, Field(ge=1, le=500)] = 100,
    ) -> CallToolResult:
        """Inspect a page of native binary strings and their addresses."""
        return await call(
            native_command("radare2_strings", identifier(binary_id), offset=offset, limit=limit)
        )

    @mcp.tool()
    async def radare2_disassemble(
        binary_id: str, address: str = "0x0", count: Annotated[int, Field(ge=1, le=256)] = 32
    ) -> CallToolResult:
        """Disassemble a bounded number of instructions at a hexadecimal address."""
        return await call(
            native_command(
                "radare2_disassemble", identifier(binary_id), location=address, count=count
            )
        )

    @mcp.tool()
    async def radare2_xrefs(binary_id: str, address: str) -> CallToolResult:
        """Analyze native cross references to a hexadecimal address."""
        return await call(native_command("radare2_xrefs", identifier(binary_id), location=address))
