"""UID-isolated provider process, reused only under one current agent identity."""

from __future__ import annotations

import asyncio
import os
import time
from contextlib import suppress

from mcp.types import CallToolRequestParams, CallToolResult

from node_protocol.effect import NodeEffectPermit

from .deferred_calls import DeferredCalls, original_call
from .domain.deferred_operations import DeferredRecord, OperationHandle, ProviderOperationBinding
from .infrastructure.worker_exchange import exchange_bytes
from .presentation.deferred_operations import ProviderOperationControl
from .process_lease import ProcessLease
from .process_lease_domain import LeaseIdentity
from .provider_ipc import (
    ProviderContext,
    decode_reply,
    encode_command,
    provider_selection,
    require_ready,
)
from .runtime_policy import child_policy_json
from .supervisor_lifecycle import _SupervisorLifecycle


class ProviderSupervisor(_SupervisorLifecycle):
    def __init__(self, module: str) -> None:
        if module not in {"svc", "infrastructure"}:
            raise ValueError("Approved provider module required")
        self.module = module
        self.lease = ProcessLease(1000)
        self.child: asyncio.subprocess.Process | None = None
        self.prepared = False
        self.lock = asyncio.Lock()
        self.warming: asyncio.Task[None] | None = None
        self.watchdog_task: asyncio.Task[None] | None = None
        self.tools: set[str] = set()
        self.active_context: ProviderContext | None = None
        self.deferred = DeferredCalls(
            module,
            lock=self.lock,
            lease=self.lease,
            ready=self.ready,
            tools=lambda: self.tools,
            execute=self.exchange_background,
            stop=self.stop,
            recover=self._schedule_warmup,
        )

    async def stop(self) -> None:
        self.prepared = False
        self.active_context = None
        self.deferred.interrupt()
        await self.lease.kill()
        if self.child is not None:
            await self.child.wait()
        self.child = None

    async def _spawn(self) -> asyncio.subprocess.Process:
        environment: dict[str, str] = {
            "BRIAREUS_RUNTIME_POLICY": child_policy_json(),
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "PYTHONPATH": "/app/src",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "HOME": "/home/hand",
            "GIT_TERMINAL_PROMPT": "0",
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "MALLOC_ARENA_MAX": "2",
            **{
                key: os.environ[key]
                for key in (
                    "HTTP_PROXY",
                    "HTTPS_PROXY",
                    "ALL_PROXY",
                    "NO_PROXY",
                    "http_proxy",
                    "https_proxy",
                    "all_proxy",
                    "no_proxy",
                )
                if key in os.environ
            },
        }
        return await asyncio.create_subprocess_exec(
            "/app/.venv/bin/python",
            "-m",
            self.module + "_hand.isolated_child",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            cwd="/app/src",
            env=environment,
            user=1000,
            group=1000,
            extra_groups=[],
            start_new_session=True,
            limit=1000001,
        )

    async def _prepare_child(self) -> None:
        self.child = await self._spawn()
        if self.child.stdout is None:
            raise ValueError("Prepared private provider output required")
        async with asyncio.timeout(120):
            raw = await self.child.stdout.readline()
        require_ready(raw)

    async def execute(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        context: ProviderContext,
    ) -> CallToolResult:
        current = context
        name = call.name
        async with self.lock:
            identity = (
                str(permit.actor_uuid),
                str(permit.agent_session_uuid),
                permit.grant_revision,
            )
            if name in {self.module + "_operation_poll", self.module + "_operation_cancel"}:
                return await self._control(call, permit, identity, current)
            if self.deferred.running():
                raise ValueError("Operation in progress; poll or cancel")
            try:
                return await self._execute_prepared(call, permit, identity, current)
            except BaseException:
                await self.stop()
                self._schedule_warmup()
                raise

    async def _execute_prepared(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        identity: LeaseIdentity,
        context: ProviderContext,
    ) -> CallToolResult:
        if not self.ready() or permit.expires_at <= time.time():
            raise ValueError("Current prepared provider required")
        previous = self.lease.identity
        preserved = await self.lease.grant(identity, permit.expires_at)
        if previous is not None and not preserved:
            raise ValueError("Fresh provider identity preparation required")
        if call.name != self.module + "_operation_start":
            return await self.exchange(call, permit, context)
        self.active_context = context
        original = original_call(call, self.tools, self.module + "_operation_")
        result = await self.deferred.start(call, permit, identity)
        self.deferred.bind_provider(
            OperationHandle(None, permit.request_uuid),
            self._provider_selection(original, context.digest()),
        )
        return result

    def _provider_selection(
        self, call: CallToolRequestParams, context_digest: str
    ) -> ProviderOperationBinding:
        return provider_selection(call, context_digest)

    def _control_record(
        self,
        command: ProviderOperationControl,
        identity: LeaseIdentity,
    ) -> DeferredRecord[CallToolResult]:
        record = self.deferred.lookup(command.handle())
        selection = command.binding()
        binding = record.provider_binding if record is not None else None
        if (
            record is None
            or binding is None
            or binding.account_id != selection.account_id
            or record.tool != command.tool
            or binding.provider != selection.provider
        ):
            raise ValueError("Exact original provider account required")
        if record.identity != identity:
            raise ValueError("Original provider identity required")
        return record

    async def _control(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        identity: LeaseIdentity,
        context: ProviderContext,
    ) -> CallToolResult:
        name = call.name
        command = ProviderOperationControl.model_validate(call.arguments or {})
        record = self._control_record(command, identity)
        binding = record.provider_binding
        if name.endswith("_poll") and (
            binding is None or binding.context_digest != context.digest()
        ):
            await self.stop()
            self._schedule_warmup()
            raise ValueError("Provider connection or policy changed; operation interrupted")
        return await self.deferred.control(
            name, command.command(polling=name.endswith("_poll")), permit, identity
        )

    async def exchange_background(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
    ) -> CallToolResult:
        try:
            if self.active_context is None:
                raise ValueError("Current project credential owner context required")
            return await self.exchange(call, permit, self.active_context, background=True)
        finally:
            self.active_context = None

    async def exchange(
        self,
        call: CallToolRequestParams,
        permit: NodeEffectPermit,
        context: ProviderContext,
        *,
        background: bool = False,
    ) -> CallToolResult:
        payload = encode_command(call, permit, context, background=background)
        raw = await exchange_bytes(
            self.child,
            payload,
            expires_at=permit.expires_at,
            background=background,
            pipes_failure="Prepared private provider pipes required",
            expired_failure="Current provider result unavailable",
        )
        return decode_reply(raw, permit.request_uuid)

    async def close(self) -> None:
        for task in (self.watchdog_task, self.warming):
            if task is not None:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
        await self.stop()
