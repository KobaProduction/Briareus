"""Original Analysis provider and native engine, isolated from signed MCP ingress."""

import asyncio
import json
import os
import time
from collections.abc import Sequence
from contextlib import AsyncExitStack, suppress
from pathlib import Path

from fastmcp import Client, FastMCP
from fastmcp.tools import Tool
from mcp.types import Tool as McpTool
from radare2_hand.domain.commands import AnalyzerCommand
from radare2_hand.runtime import Analyzer, AnalyzerResult
from radare2_hand.tools import register_tools as register_radare2_tools

from common.settings import AnalysisSettings
from hand_runtime.runtime_policy import runtime_policy
from modules.analysis.provider import AnalysisToolProvider
from modules.analysis.terminology import analysis_tool_name

from .analysis_facade import register_facade
from .domain.dispatch import Engine
from .infrastructure.child_io import serve_requests
from .infrastructure.engine_dispatch import (
    AnalysisIngress,
    EngineClient,
    McpEngineExecution,
    NativeDeadline,
    engine_catalogue,
)
from .infrastructure.engine_storage import prepare_storage
from .node_runtime import GhidraRuntime
from .project_transfer import register_transfer

UNAVAILABLE_TOOLS = frozenset(
    {
        "run_analysis_script",
        "run_analysis_script_inline",
        "connect_repository_service",
        "disconnect_repository_service",
        "stop_analysis_runtime",
    }
)


class NodeAnalysisProvider(AnalysisToolProvider):
    def _adapt_catalog(self, backend_tools: Sequence[McpTool]) -> list[Tool]:
        # Existing workspace transfer goes through these exact original staged
        # upload callables. Here the project-private engine owns the input, so
        # expose their original bounded schemas directly instead of mounting a
        # global Files workspace or forwarding a caller-selected network URL.
        tools = super()._adapt_catalog(backend_tools)
        aliases = {tool.name: analysis_tool_name(tool.name) for tool in backend_tools}
        for tool in backend_tools:
            if tool.name.startswith("artifact_stage_"):
                tools.append(self._adapt_tool(tool, aliases[tool.name], aliases))
        return [tool for tool in tools if tool.name not in UNAVAILABLE_TOOLS]


async def main() -> None:
    status = await asyncio.to_thread(Path("/proc/self/status").read_text)
    facts = dict(line.split(":", 1) for line in status.splitlines() if ":" in line)
    if os.geteuid() != 1000 or os.getegid() != 1000 or int(facts["CapEff"].strip(), 16) != 0:
        raise ValueError("Unprivileged private Analysis runtime required")
    os.chdir("/project-data")
    storage = prepare_storage(Path("/project-data"))
    runtime = GhidraRuntime(storage.ghidra, int(os.environ["BRIAREUS_ANALYSIS_MEMORY_BYTES"]))
    radare = Analyzer(storage.radare2)
    provider = NodeAnalysisProvider(
        AnalysisSettings(
            backend_url="http://127.0.0.1:8081/mcp",
            direct_upload_url="",
            schema_cache_ttl_seconds=0,
        )
    )
    await runtime.start()
    watchdog: asyncio.Task[None] | None = None
    try:
        await radare.startup()
        ghidra_mcp = FastMCP[None]("private-ghidra")
        tools = await provider._list_tools()
        for tool in tools:
            ghidra_mcp.add_tool(tool)
        register_transfer(ghidra_mcp, provider)
        tools = await ghidra_mcp.list_tools()
        deadline = NativeDeadline()

        async def execute_radare(command: AnalyzerCommand) -> AnalyzerResult:
            return await radare.execute(command, deadline)

        radare_mcp = FastMCP[None]("private-radare2")
        register_radare2_tools(radare_mcp, execute_radare)
        engine_tools: dict[Engine, Sequence[Tool]] = {
            "ghidra": tools,
            "radare2": await radare_mcp.list_tools(),
        }
        engine_catalogues = {
            engine: engine_catalogue(engine, values) for engine, values in engine_tools.items()
        }
        facade = FastMCP[None]("isolated-analysis")
        register_facade(facade)
        public_tools = await facade.list_tools()
        names = {tool.name for tool in public_tools}
        catalogue = [
            tool.model_dump(
                mode="json",
                include={
                    "name",
                    "title",
                    "description",
                    "parameters",
                    "output_schema",
                    "annotations",
                },
            )
            for tool in public_tools
        ]
        first = json.dumps({"ready": True, "tools": catalogue}, allow_nan=False)
        if len(first.encode()) > 1_000_000:
            raise ValueError("Bounded original Analysis catalogue required")

        async def monitor() -> None:
            await runtime.wait_stopped()
            # Native failure cannot leave the supervisor reporting ready.
            os._exit(70)

        watchdog = asyncio.create_task(monitor())
        async with AsyncExitStack() as stack:
            clients: dict[Engine, EngineClient] = {
                "ghidra": await stack.enter_async_context(Client(ghidra_mcp, timeout=None)),
                "radare2": await stack.enter_async_context(Client(radare_mcp, timeout=None)),
            }
            print(first, flush=True)
            dispatch = AnalysisIngress(
                engine_catalogues,
                McpEngineExecution(clients, deadline, engine_tools),
                time.time,
                runtime_policy().execution_timeout_seconds,
            )
            await serve_requests(dispatch, frozenset(names), runtime.current)
    finally:
        if watchdog is not None:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog
        await provider._backend_pool.close()
        await radare.close()
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
