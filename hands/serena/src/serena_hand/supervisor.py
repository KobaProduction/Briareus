"""Trusted Node parent; Serena and all LSP descendants have a separate UID."""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import suppress

from fastmcp.tools import Tool as MetadataTool
from mcp.types import CallToolRequestParams, CallToolResult

from hand_runtime.deferred_calls import DeferredCalls
from hand_runtime.infrastructure.worker_exchange import exchange_bytes
from hand_runtime.presentation.deferred_operations import (
    CancelOperationRequest,
    PollOperationRequest,
)
from hand_runtime.process_lease import ProcessLease
from hand_runtime.runtime_policy import child_policy_json
from hand_runtime.supervisor_lifecycle import _SupervisorLifecycle
from node_protocol.effect import NodeEffectPermit
from serena_hand.application.acquire_session import AcquireSessionAuthority
from serena_hand.domain.session import require_original_catalogue
from serena_hand.infrastructure.parent_codec import (
    decode_catalogue,
    decode_reply,
    encode_command,
)


class SerenaSupervisor(_SupervisorLifecycle):
    def __init__(self, project_path: str) -> None:
        self.project_path = project_path
        self.lease = ProcessLease(1000)
        self.child: asyncio.subprocess.Process | None = None
        self.prepared = False
        self.catalogue: tuple[MetadataTool, ...] | None = None
        self.catalogue_signature: str | None = None
        self.lock = asyncio.Lock()
        self.warming: asyncio.Task[None] | None = None
        self.watchdog_task: asyncio.Task[None] | None = None
        self.deferred = DeferredCalls(
            "serena",
            lock=self.lock,
            lease=self.lease,
            ready=self.ready,
            tools=self.tool_names,
            execute=self.exchange_background,
            stop=self.stop,
            recover=self._schedule_warmup,
        )

    def tool_names(self) -> set[str]:
        return {item.name for item in self.catalogue or ()}

    async def stop(self) -> None:
        self.prepared = False
        self.deferred.interrupt()
        await self.lease.kill()
        if self.child is not None:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None

    async def _prepare_child(self) -> None:
        environment: dict[str, str] = {
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": "/app/src",
            "HOME": "/home/hand",
            "SERENA_HOME": "/home/hand/.serena",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "BRIAREUS_SERENA_PROJECT_PATH": self.project_path,
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "MALLOC_ARENA_MAX": "2",
        }
        environment["BRIAREUS_RUNTIME_POLICY"] = child_policy_json()
        self.child = await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python",
            "-m",
            "serena_hand.isolated_child",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd="/app/src",
            user=1000,
            group=1000,
            extra_groups=[],
            start_new_session=True,
            env=environment,
            limit=1000001,
        )
        stdout = self.child.stdout
        if stdout is None:
            raise ValueError("Private Serena output pipe required")
        async with asyncio.timeout(180):
            raw = await stdout.readline()
        first = decode_catalogue(raw)
        signature = json.dumps(json.loads(raw), sort_keys=True, allow_nan=False)
        require_original_catalogue(self.catalogue_signature, signature)
        self.catalogue_signature = signature
        self.catalogue = tuple(first.tools)

    async def call(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
    ) -> CallToolResult:
        name = call.name
        async with self.lock:
            identity = (
                str(permit.actor_uuid),
                str(permit.agent_session_uuid),
                permit.grant_revision,
            )
            if name in {"serena_operation_poll", "serena_operation_cancel"}:
                model = PollOperationRequest if name.endswith("_poll") else CancelOperationRequest
                command = model.model_validate(call.arguments or {})
                return await self.deferred.control(name, command, permit, identity)
            if self.deferred.running():
                raise ValueError("Serena operation in progress; poll or cancel it first")
            try:
                await AcquireSessionAuthority(self.lease.grant, self.ready, time.time).execute(
                    identity,
                    permit.expires_at,
                    existing_identity=self.lease.identity is not None,
                )
                if name == "serena_operation_start":
                    return CallToolResult.model_validate(
                        await self.deferred.start(call, permit, identity)
                    )
                return await self.exchange(call, permit)
            except BaseException:
                # A timed-out request is never replayed after resuming a process.
                await self.stop()
                self._schedule_warmup()
                raise

    async def exchange_background(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
    ) -> CallToolResult:
        return await self.exchange(call, permit, background=True)

    async def exchange(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        *,
        background: bool = False,
    ) -> CallToolResult:
        operation = permit.request_uuid
        payload = encode_command(call, permit, background=background)
        # Waiting for IPC is not authority: the UID watchdog still stops all
        # native descendants after the short grant, including LSP processes.
        raw = await exchange_bytes(
            self.child,
            payload,
            expires_at=permit.expires_at,
            background=background,
            pipes_failure="Prepared private Serena pipes required",
            expired_failure="Serena result expired or unavailable",
        )
        return decode_reply(raw, operation)

    async def close(self) -> None:
        if self.watchdog_task is not None:
            self.watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watchdog_task
        if self.warming is not None:
            self.warming.cancel()
            with suppress(asyncio.CancelledError):
                await self.warming
        await self.stop()
