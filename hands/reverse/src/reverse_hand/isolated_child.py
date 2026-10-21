"""Original Analysis provider and native engine, isolated from signed MCP ingress."""
from hand_runtime.runtime_policy import runtime_policy
import asyncio
import json
import os
import sys
import time
from contextlib import suppress
from pathlib import Path
from uuid import UUID
from types import SimpleNamespace
from contextlib import AsyncExitStack

from fastmcp import Client, FastMCP
from common.settings import AnalysisSettings
from modules.analysis.provider import AnalysisToolProvider
from modules.analysis.terminology import analysis_tool_name
from .node_runtime import GhidraRuntime
from .analysis_facade import register_facade
from radare2_hand.runtime import Analyzer
from radare2_hand.tools import register_tools as register_radare2_tools

UNAVAILABLE_TOOLS = frozenset({"run_analysis_script", "run_analysis_script_inline",
    "connect_repository_service", "disconnect_repository_service", "stop_analysis_runtime"})


class NodeAnalysisProvider(AnalysisToolProvider):
    def _adapt_catalog(self, backend_tools):
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


async def main():
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if os.geteuid() != 1000 or os.getegid() != 1000 or int(facts["CapEff"].strip(), 16) != 0:
        raise ValueError("Unprivileged private Analysis runtime required")
    os.chdir("/project-data")
    root = Path("/project-data")
    for name in ("ghidra", "radare2"):
        directory = root / name
        directory.mkdir(mode=0o700, exist_ok=True)
        if directory.is_symlink() or not directory.is_dir():
            raise ValueError("Separate private engine storage required")
        os.chmod(directory, 0o700)
    runtime = GhidraRuntime(root / "ghidra", int(os.environ["BRIAREUS_ANALYSIS_MEMORY_BYTES"]))
    radare = Analyzer(root / "radare2")
    provider = NodeAnalysisProvider(AnalysisSettings(
        backend_url="http://127.0.0.1:8081/mcp", direct_upload_url="", schema_cache_ttl_seconds=0))
    await runtime.start()
    watchdog = None
    try:
        await radare.startup()
        ghidra_mcp = FastMCP("private-ghidra")
        tools = await provider._list_tools()
        for tool in tools:
            ghidra_mcp.add_tool(tool)
        from .project_transfer import register_transfer
        register_transfer(ghidra_mcp,provider)
        tools = await ghidra_mcp.list_tools()
        deadline = 0

        async def execute_radare(name, arguments):
            return await radare.execute(name, arguments, SimpleNamespace(expires_at=deadline))

        radare_mcp = FastMCP("private-radare2")
        register_radare2_tools(radare_mcp, execute_radare)
        engine_tools = {"ghidra": tools, "radare2": await radare_mcp.list_tools()}
        engine_catalogues = {engine: [dict(name=tool.name, description=tool.description,
            inputSchema=tool.parameters, outputSchema=tool.output_schema, annotations=(
                tool.annotations.model_dump(mode="json") if tool.annotations else None)) for tool in values]
            for engine, values in engine_tools.items()}
        engine_names = {engine: {tool.name for tool in values} for engine, values in engine_tools.items()}
        facade = FastMCP("isolated-analysis")
        register_facade(facade)
        public_tools = await facade.list_tools()
        names = {tool.name for tool in public_tools}
        catalogue = [tool.model_dump(mode="json", include={"name", "title", "description",
                     "parameters", "output_schema", "annotations"}) for tool in public_tools]
        first = json.dumps({"ready": True, "tools": catalogue}, allow_nan=False)
        if len(first.encode()) > 1_000_000:
            raise ValueError("Bounded original Analysis catalogue required")

        async def monitor():
            while runtime.current():
                await asyncio.sleep(0.25)
            # Native failure cannot leave the supervisor reporting ready.
            os._exit(70)

        watchdog = asyncio.create_task(monitor())
        async with AsyncExitStack() as stack:
            clients = {"ghidra": await stack.enter_async_context(Client(ghidra_mcp, timeout=None)),
                       "radare2": await stack.enter_async_context(Client(radare_mcp, timeout=None))}
            print(first, flush=True)
            while True:
                line = await asyncio.to_thread(sys.stdin.buffer.readline, 32769)
                if not line:
                    return
                if len(line) > 32768:
                    raise ValueError("Bounded supervisor input required")
                request = json.loads(line)
                if (not isinstance(request, dict) or set(request) != {"id", "tool", "arguments", "expires_at"}
                    or UUID(request["id"]).version != 4 or request["tool"] not in names
                    or not isinstance(request["arguments"], dict) or type(request["expires_at"]) is not int
                    or not 0 < request["expires_at"] - time.time() <= 5 or not runtime.current()):
                    raise ValueError("Exact current Analysis request required")
                try:
                    arguments = request["arguments"]
                    engine = arguments.get("engine")
                    if engine not in engine_catalogues:
                        raise ValueError("Known analysis engine required")
                    deadline = None if request["tool"]=="analysis_start" else request["expires_at"]
                    # Long operations are supervised by the trusted parent's
                    # short ProcessLease, renewed only by authorized polls.
                    # This private timeout is a bounded job lifetime, NEVER a
                    # replacement for the current Core execution permit.
                    long_operation = request["tool"] == "analysis_start"
                    async with asyncio.timeout(runtime_policy().execution_timeout_seconds if long_operation else max(0, request["expires_at"] - time.time())):
                        if request["tool"] == "analysis_tools":
                            if set(arguments) != {"engine"}:
                                raise ValueError("Exact analysis catalogue selector required")
                            payload = {"engine": engine, "tools": engine_catalogues[engine]}
                            result = {"content": [{"type": "text", "text":
                                f"Actual {engine} catalogue: {len(engine_catalogues[engine])} tools; schemas in structuredContent"}],
                                      "structuredContent": payload, "isError": False}
                        else:
                            if (set(arguments) != {"engine", "tool", "arguments"}
                                or not isinstance(arguments["tool"], str)
                                or arguments["tool"] not in engine_names[engine]
                                or not isinstance(arguments["arguments"], dict)):
                                raise ValueError("Exact actual engine tool and arguments required")
                            value = await clients[engine].call_tool(arguments["tool"], arguments["arguments"], raise_on_error=False)
                            result = {"content": [item.model_dump(mode="json", by_alias=True) for item in value.content],
                                      "structuredContent": value.structured_content, "isError": value.is_error}
                except TimeoutError:
                    # Cancelling HTTP does not prove that a JVM effect stopped.
                    # Exit and let the trusted parent kill every execution UID.
                    raise
                except Exception:
                    result = {"content": [{"type": "text", "text": "REVERSE_OPERATION_REJECTED_OR_UNAVAILABLE"}], "isError": True}
                reply = json.dumps({"id": request["id"], "result": result}, separators=(",", ":"), allow_nan=False)
                if len(reply.encode()) > 1_000_000:
                    raise ValueError("Bounded Analysis result required")
                print(reply, flush=True)
    finally:
        if watchdog:
            watchdog.cancel()
            with suppress(asyncio.CancelledError):
                await watchdog
        await provider._backend_pool.close()
        await radare.close()
        await runtime.close()


if __name__ == "__main__":
    asyncio.run(main())
