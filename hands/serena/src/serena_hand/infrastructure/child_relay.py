"""Private bounded wire codec and pinned upstream MCP session adapter."""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

from fastmcp.tools import Tool as MetadataTool
from mcp import ClientSession
from mcp.types import CallToolRequestParams, CallToolResult, TextContent, Tool
from pydantic import BaseModel

from hand_runtime.provider_results import ProviderReply
from serena_hand.application.dispatch_effect import DispatchEffect
from serena_hand.confinement import confine_arguments
from serena_hand.domain.effects import IsolationFacts, require_catalogue
from serena_hand.runtime import BLOCKED_TOOLS, UPSTREAM_VERSION, prepare_project

from .private_messages import PrivateRequest, ReadyCatalogue


def require_isolation() -> None:
    facts = dict(
        line.split(":", 1)
        for line in Path("/proc/self/status").read_text().splitlines()
        if ":" in line
    )
    IsolationFacts(
        os.geteuid(),
        os.getegid(),
        facts["NoNewPrivs"].strip() == "1",
        int(facts["CapEff"].strip(), 16),
        bool(os.statvfs("/").f_flag & os.ST_RDONLY),
        frozenset(item.name for item in Path("/sys/class/net").iterdir()),
    ).require_isolated()


def bounded_json(value: BaseModel) -> str:
    payload = json.dumps(
        value.model_dump(mode="json", by_alias=True, exclude_none=True),
        allow_nan=False,
    )
    if len(payload.encode()) > 1000000:
        raise ValueError("Bounded Serena result required")
    return payload


def catalogue_tool(tool: Tool) -> MetadataTool:
    return MetadataTool(
        name=tool.name,
        title=tool.title,
        description=tool.description,
        parameters=tool.input_schema,
        output_schema=tool.output_schema,
        annotations=tool.annotations,
    )


async def announce(session: ClientSession) -> frozenset[str]:
    initialized = await session.initialize()
    tools = [
        tool
        for tool in (await session.list_tools()).tools
        if tool.name not in BLOCKED_TOOLS and not tool.name.startswith("jet_brains_")
    ]
    names = frozenset(tool.name for tool in tools)
    require_catalogue(initialized.server_info.version, UPSTREAM_VERSION, names)
    catalogue = ReadyCatalogue(ready=True, tools=[catalogue_tool(tool) for tool in tools])
    payload = catalogue.model_dump_json(
        include={
            "ready": True,
            "tools": {
                "__all__": {
                    "name",
                    "title",
                    "description",
                    "parameters",
                    "output_schema",
                    "annotations",
                }
            },
        }
    )
    if len(payload.encode()) > 1000000:
        raise ValueError("Bounded original Serena catalogue required")
    print(payload, flush=True)
    return names


@dataclass(frozen=True)
class UpstreamEffect:
    session: ClientSession
    request: PrivateRequest
    project: Path

    async def execute(self) -> CallToolResult:
        try:
            call = confine_arguments(self.request.call, self.project)
            if call.name == "activate_project":
                prepare_project(os.environ["BRIAREUS_SERENA_PROJECT_PATH"])
                call = CallToolRequestParams(
                    name=call.name,
                    arguments={**(call.arguments or {}), "project": str(self.project)},
                )
            return await self.session.call_tool(call.name, call.arguments)
        except Exception:
            return CallToolResult(
                content=[TextContent(type="text", text="SERENA_OPERATION_REJECTED_OR_UNAVAILABLE")],
                is_error=True,
            )


class SystemClock:
    def now(self) -> float:
        return time.time()


async def relay(session: ClientSession, project: Path, names: frozenset[str]) -> None:
    dispatch = DispatchEffect(SystemClock(), names)
    while True:
        line = await asyncio.to_thread(sys.stdin.buffer.readline, 32769)
        if not line:
            return
        if len(line) > 32768 or not line.endswith(b"\n"):
            raise ValueError("Bounded private Serena request required")
        request = PrivateRequest.model_validate_json(line)
        authority = request.authority()
        result = await dispatch.execute(authority, UpstreamEffect(session, request, project))
        print(bounded_json(ProviderReply(id=request.id, result=result)), flush=True)
