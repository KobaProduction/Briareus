"""Private process protocol; the native child receives only its bounded environment."""

import asyncio
import os
import time
from dataclasses import dataclass

from fastmcp.tools import Tool
from mcp.types import CallToolRequestParams, CallToolResult

from hand_runtime.analysis_call import AnalysisCommand
from hand_runtime.domain.deferred_operations import OperationAuthority
from hand_runtime.runtime_policy import child_policy_json, runtime_policy
from reverse_hand.infrastructure.operation_wire import AnalysisChildCatalogue, AnalysisChildReply


@dataclass(frozen=True, slots=True)
class PreparedChild:
    process: asyncio.subprocess.Process
    catalogue: tuple[Tool, ...]


async def spawn_child(module: str, memory_bytes: int | None) -> asyncio.subprocess.Process:
    environment: dict[str, str] = {
        "BRIAREUS_RUNTIME_POLICY": child_policy_json(),
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "PYTHONPATH": "/app/src",
        "HOME": "/home/hand",
        "BRIAREUS_PROJECT_TRANSFER": os.environ.get("BRIAREUS_PROJECT_TRANSFER", "0"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONUNBUFFERED": "1",
    }
    if memory_bytes:
        environment["BRIAREUS_ANALYSIS_MEMORY_BYTES"] = str(memory_bytes)
    return await asyncio.create_subprocess_exec(
        "/app/.venv/bin/python",
        "-m",
        module,
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        cwd="/app/src",
        user=1000,
        group=1000,
        extra_groups=[],
        start_new_session=True,
        env=environment,
        limit=1_000_001,
    )


async def prepare_child(child: asyncio.subprocess.Process) -> PreparedChild:
    if child.stdout is None:
        raise ValueError("Analysis child output required")
    async with asyncio.timeout(125):
        raw = await child.stdout.readline()
    if not raw or len(raw) > 1_000_000:
        raise ValueError("Bounded analysis child metadata required")
    first = AnalysisChildCatalogue.model_validate_json(raw)
    if not first.ready:
        raise ValueError("Analysis child did not prepare its real runtime")
    return PreparedChild(child, first.tools)


async def exchange(
    child: asyncio.subprocess.Process,
    call: CallToolRequestParams,
    authority: OperationAuthority,
    *,
    long: bool,
) -> CallToolResult:
    payload = AnalysisCommand(
        id=authority.request_uuid, call=call, expires_at=authority.expires_at
    ).encode()
    if child.stdin is None or child.stdout is None:
        raise ValueError("Prepared analysis child streams required")
    timeout = (
        runtime_policy().execution_timeout_seconds
        if long
        else max(0, authority.expires_at - time.time())
    )
    async with asyncio.timeout(timeout):
        child.stdin.write(payload)
        await child.stdin.drain()
        raw = await child.stdout.readline()
        if not raw or len(raw) > 1_000_000 or (not long and authority.expires_at <= time.time()):
            raise ValueError("Analysis outcome expired or unavailable")
        reply = AnalysisChildReply.model_validate_json(raw)
        if reply.id != str(authority.request_uuid):
            raise ValueError("Bounded correlated analysis result required")
        return reply.result
