"""Unprivileged parser process: no bearer, signing material or Core context."""

import asyncio
import json
import os
import sys
import time
from pathlib import Path

from fastmcp import Client, FastMCP
from mcp.types import CallToolResult, TextContent

from hand_runtime.provider_results import ProviderReply

from .domain.commands import AnalyzerCommand, NativeDeadline
from .infrastructure.child_protocol import decode_call
from .runtime import Analyzer, AnalyzerResult
from .tools import register_tools


async def main() -> None:
    status = await asyncio.to_thread(Path("/proc/self/status").read_text)
    facts = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if os.geteuid() != 1000 or os.getegid() != 1000 or int(facts["CapEff"].strip(), 16) != 0:
        raise ValueError("Unprivileged analysis execution identity required")
    os.chdir("/project-data")
    analyzer = Analyzer(Path("/project-data"))
    deadline = NativeDeadline()

    async def execute(command: AnalyzerCommand) -> AnalyzerResult:
        return await analyzer.execute(command, deadline)

    mcp = FastMCP[None]("private-radare2")
    register_tools(mcp, execute)
    await analyzer.startup()
    try:
        async with Client(mcp, timeout=None) as client:
            allowed = frozenset(tool.name for tool in await client.list_tools())
            print(json.dumps({"ready": True}), flush=True)
            while True:
                line = await asyncio.to_thread(sys.stdin.buffer.readline, 32769)
                if not line:
                    return
                if len(line) > 32768:
                    raise ValueError("Bounded supervisor input required")
                request = decode_call(line, allowed, time.time())
                deadline.expires_at = request.expires_at
                try:
                    async with asyncio.timeout(max(0, request.expires_at - time.time())):
                        value = await client.call_tool(
                            request.call.name, request.call.arguments or {}, raise_on_error=False
                        )
                    result = CallToolResult(
                        content=value.content,
                        structured_content=value.structured_content,
                        is_error=value.is_error,
                        meta=value.meta,
                    )
                except (ValueError, TypeError, KeyError, OSError, TimeoutError):
                    result = CallToolResult(
                        content=[
                            TextContent(
                                type="text", text="RADARE2_OPERATION_REJECTED_OR_UNAVAILABLE"
                            )
                        ],
                        is_error=True,
                    )
                print(ProviderReply(id=request.id, result=result).encode(), flush=True)
    finally:
        await analyzer.close()


if __name__ == "__main__":
    asyncio.run(main())
