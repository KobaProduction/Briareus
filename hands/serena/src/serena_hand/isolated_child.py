"""UID1000 relay to the real pinned Serena MCP stdio server and LSP processes."""
from __future__ import annotations
import asyncio
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import time
from uuid import UUID
from mcp import ClientSession
from mcp.client.stdio import stdio_client
from .confinement import confine_arguments
from .runtime import prepare_project, server_parameters, BLOCKED_TOOLS, UPSTREAM_VERSION


def require_isolation():
    facts = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines() if ":" in line)
    if (os.geteuid() != 1000 or os.getegid() != 1000 or facts["NoNewPrivs"].strip() != "1"
        or int(facts["CapEff"].strip(), 16) != 0 or not os.statvfs("/").f_flag & os.ST_RDONLY
        or {item.name for item in Path("/sys/class/net").iterdir()} != {"lo"}):
        raise ValueError("Offline unprivileged readonly-root Serena runtime required")


async def main():
    require_isolation()
    if importlib.metadata.version("serena-agent") != UPSTREAM_VERSION:
        raise ValueError("Exact pinned upstream Serena is required")
    project = prepare_project(os.environ["BRIAREUS_SERENA_PROJECT_PATH"])
    os.chdir(project)
    with open(os.devnull, "w") as diagnostics:
        async with stdio_client(server_parameters(project), errlog=diagnostics) as (read, write):
            async with ClientSession(read, write) as session:
                initialized = await session.initialize()
                if initialized.server_info.version != UPSTREAM_VERSION:
                    raise ValueError("Actual pinned Serena server metadata required")
                tools = (await session.list_tools()).tools
                tools = [tool for tool in tools if tool.name not in BLOCKED_TOOLS and not tool.name.startswith("jet_brains_")]
                names = {tool.name for tool in tools}
                required = {"initial_instructions", "activate_project", "find_symbol", "get_symbols_overview",
                            "find_referencing_symbols", "replace_symbol_body", "rename_symbol", "execute_shell_command"}
                if not required <= names:
                    raise ValueError("Actual complete Serena LSP tools required")
                # MCP can serve its real tool catalogue with no active project.
                # LSP readiness belongs to explicit project activation, not to
                # startup of a module whose shared workspace can still be empty.
                catalogue = [{"name": tool.name, "title": tool.title, "description": tool.description,
                              "parameters": tool.input_schema, "output_schema": tool.output_schema,
                              "annotations": tool.annotations.model_dump(mode="json", by_alias=True) if tool.annotations else None}
                             for tool in tools]
                first = json.dumps({"ready": True, "tools": catalogue}, allow_nan=False)
                if len(first.encode()) > 1000000:
                    raise ValueError("Bounded original Serena catalogue required")
                print(first, flush=True)
                while True:
                    line = await asyncio.to_thread(sys.stdin.buffer.readline, 32769)
                    if not line:
                        return
                    if len(line) > 32768 or not line.endswith(b"\n"):
                        raise ValueError("Bounded private Serena request required")
                    request = json.loads(line)
                    if (not isinstance(request, dict) or set(request) not in (
                            {"id", "tool", "arguments", "expires_at"},
                            {"id", "tool", "arguments", "expires_at", "background"})
                        or type(request.get('background',False)) is not bool
                        or UUID(request["id"]).version != 4 or request["tool"] not in names
                        or not isinstance(request["arguments"], dict)
                        or type(request["expires_at"]) not in (int, float)
                        or not 0 < request["expires_at"] - time.time() <= 5):
                        raise ValueError("Current exact Serena effect required")
                    try:
                        arguments = confine_arguments(request["tool"], request["arguments"], project)
                        if request["tool"] == "activate_project":
                            # Refresh language config after files arrive, then
                            # resolve the validated placement alias to its exact
                            # path before calling the original upstream tool.
                            prepare_project(os.environ["BRIAREUS_SERENA_PROJECT_PATH"])
                            arguments = dict(arguments, project=str(project))
                        value = await session.call_tool(request["tool"], arguments)
                        result = value.model_dump(mode="json", by_alias=True, exclude_none=True)
                    except Exception:
                        result = {"content": [{"type": "text", "text": "SERENA_OPERATION_REJECTED_OR_UNAVAILABLE"}],
                                  "isError": True}
                    if not request.get('background',False) and request["expires_at"] <= time.time():
                        raise ValueError("Serena outcome expired")
                    reply = json.dumps({"id": request["id"], "result": result}, allow_nan=False)
                    if len(reply.encode()) > 1000000:
                        raise ValueError("Bounded Serena result required")
                    print(reply, flush=True)


if __name__ == "__main__":
    asyncio.run(main())
