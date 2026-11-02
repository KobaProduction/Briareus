"""Trusted rootless parent; native parsers never share its UID or memory."""

import asyncio
import time
from contextlib import suppress

from mcp.types import CallToolRequestParams, CallToolResult, Tool

from hand_runtime.process_lease import ProcessLease
from hand_runtime.provider_ipc import decode_reply
from node_protocol.effect import NodeEffectPermit
from service_runtime._isolated_supervisor_state import _IsolatedSupervisorState

from .infrastructure.child_protocol import ChildReady, encode_call


class IsolatedSupervisor(_IsolatedSupervisorState[ProcessLease]):
    def __init__(self, child_module: str, memory_bytes: int | None = None) -> None:
        self.child_module = child_module
        self.memory_bytes = memory_bytes
        self.child: asyncio.subprocess.Process | None = None
        self.prepared = False
        self.lock = asyncio.Lock()
        self.warming: asyncio.Task[None] | None = None
        self.catalogue: tuple[Tool, ...] | None = None
        self.lease = ProcessLease()
        self.watchdog_task: asyncio.Task[None] | None = None

    async def stop(self) -> None:
        self.prepared = False
        await self.lease.kill()
        if self.child:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None

    async def _prepare_child(self) -> None:
        self.child = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python",
            "-m",
            self.child_module,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd="/app/src",
            user=1000,
            group=1000,
            extra_groups=[],
            start_new_session=True,
            env={
                "PATH": "/usr/local/bin:/usr/bin:/bin",
                "PYTHONPATH": "/app/src",
                "HOME": "/home/hand",
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                **(
                    {"BRIAREUS_ANALYSIS_MEMORY_BYTES": str(self.memory_bytes)}
                    if self.memory_bytes
                    else {}
                ),
            },
            limit=1_000_001,
        )
        if self.child.stdout is None:
            raise ValueError("Private analysis child output required")
        async with asyncio.timeout(125):
            raw = await self.child.stdout.readline()
        if not raw or len(raw) > 1_000_000:
            raise ValueError("Bounded analysis child metadata required")
        first = ChildReady.model_validate_json(raw)
        if not first.ready:
            raise ValueError("Analysis child did not prepare its real runtime")
        self.catalogue = first.tools

    async def call(self, call: CallToolRequestParams, permit: NodeEffectPermit) -> CallToolResult:
        async with self.lock:
            try:
                if not self.ready() or permit.expires_at <= time.time():
                    raise ValueError("Current prepared analysis runtime required")
                identity = (
                    str(permit.actor_uuid),
                    str(permit.agent_session_uuid),
                    permit.grant_revision,
                )
                prior = self.lease.identity
                preserved = await self.lease.grant(identity, permit.expires_at)
                if prior is not None and not preserved:
                    # A different actor/session/revision never resumes old native
                    # execution. Prepare a clean runtime outside this call.
                    raise ValueError("Native execution identity changed; clean warmup required")
                payload = encode_call(call, permit)
                child = self.child
                if child is None or child.stdin is None or child.stdout is None:
                    raise ValueError("Prepared private analysis streams required")
                async with asyncio.timeout(max(0, permit.expires_at - time.time())):
                    child.stdin.write(payload)
                    await child.stdin.drain()
                    raw = await child.stdout.readline()
                    if not raw or len(raw) > 1_000_000 or permit.expires_at <= time.time():
                        raise ValueError("Analysis outcome expired or unavailable")
                    return decode_reply(raw, permit.request_uuid)
            except BaseException:
                await self.stop()
                self.warming = asyncio.create_task(self.warmup())
                self.warming.add_done_callback(
                    lambda task: None if task.cancelled() else task.exception()
                )
                raise

    async def close(self) -> None:
        if self.watchdog_task:
            self.watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watchdog_task
        if self.warming:
            self.warming.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming
        await self.stop()
