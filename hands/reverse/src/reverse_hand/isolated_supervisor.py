"""Trusted rootless composition root for private Analysis runtime and operation use cases."""

import asyncio
import json
import logging
import time
from contextlib import suppress
from dataclasses import dataclass
from uuid import uuid4

from fastmcp.tools import Tool
from mcp.types import CallToolRequestParams, CallToolResult, TextContent

from hand_runtime.domain.deferred_operations import OperationHandle, OperationState
from hand_runtime.errors import NodePreparing
from hand_runtime.presentation.deferred_operations import (
    CancelOperationRequest,
    operation_handle_wire,
)
from hand_runtime.process_lease import ProcessLease
from hand_runtime.process_lease_domain import LeaseIdentity
from node_protocol.effect import EffectPermit, HumanEffectPermit
from service_runtime._isolated_supervisor_state import _IsolatedSupervisorState

from .application.operations import (
    AdmitAnalysisExecution,
    AnalysisPreparing,
    OperationAuthority,
    PollAnalysisOperation,
)
from .domain.dispatch import Engine
from .domain.operations import AnalysisOperation, OperationInventory
from .infrastructure.analysis_requests import engine_invocation
from .infrastructure.operation_wire import AnalysisOperationView
from .infrastructure.supervisor_io import exchange as child_exchange
from .infrastructure.supervisor_io import prepare_child, spawn_child

LOG = logging.getLogger(__name__)
RECOVERY_DELAYS = (0, 5, 15)


@dataclass(slots=True)
class OperationExecution:
    operation: AnalysisOperation
    task: asyncio.Task[None] | None = None
    result: CallToolResult | None = None


def operation_authority(permit: EffectPermit) -> OperationAuthority:
    if isinstance(permit, HumanEffectPermit):
        return OperationAuthority(
            request_uuid=permit.request_uuid,
            identity=(
                "human",
                str(permit.actor_uuid),
                str(permit.project_uuid),
                permit.resource_revision,
            ),
            expires_at=permit.expires_at,
        )
    return OperationAuthority(
        request_uuid=permit.request_uuid,
        identity=(str(permit.actor_uuid), str(permit.agent_session_uuid), permit.grant_revision),
        expires_at=permit.expires_at,
    )


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
        self.closed = False
        self.inventory = OperationInventory(uuid4())
        self.operations: dict[OperationHandle, OperationExecution] = {}
        self.poll_operation = PollAnalysisOperation(self.inventory, self)
        self.admit_execution = AdmitAnalysisExecution(self)

    def lease_identity(self) -> LeaseIdentity | None:
        return self.lease.identity

    async def renew(self, authority: OperationAuthority) -> bool:
        return await self.lease.grant(authority.identity, authority.expires_at)

    def schedule_recovery(self) -> None:
        if self.closed or (self.warming is not None and not self.warming.done()):
            return
        self.warming = asyncio.create_task(self.recover())

    async def recover(self) -> None:
        """Retry preparation only; a failed native effect is never replayed."""
        for attempt, delay in enumerate(RECOVERY_DELAYS, 1):
            if self.closed:
                return
            await asyncio.sleep(delay)
            try:
                await self.warmup()
                return
            except Exception:
                LOG.warning(
                    "Analysis metadata preparation failed (attempt %d/%d)",
                    attempt,
                    len(RECOVERY_DELAYS),
                )

    async def stop(self) -> None:
        self.prepared = False
        await self.lease.kill()
        for execution in self.operations.values():
            if execution.operation.interrupt():
                task = execution.task
                if task is not None and task is not asyncio.current_task():
                    task.cancel()
        if self.child:
            with suppress(ProcessLookupError):
                await self.child.wait()
        self.child = None

    def outcome(self, record: AnalysisOperation) -> CallToolResult:
        view = AnalysisOperationView(
            operation_id=operation_handle_wire(record.operation_id),
            engine=record.engine,
            tool=record.tool,
            state=record.state,
        )
        execution = self.operations[record.operation_id]
        if execution.result is not None:
            view = view.model_copy(update={"result": execution.result})
        return CallToolResult(
            content=[TextContent(type="text", text="Analysis operation: " + record.state)],
            structured_content=view.model_dump(mode="json", by_alias=True, exclude_unset=True),
            is_error=False,
        )

    async def exchange(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
        *,
        long: bool = False,
    ) -> CallToolResult:
        if self.child is None:
            raise ValueError("Original prepared analysis runtime required")
        return await child_exchange(self.child, call, operation_authority(permit), long=long)

    async def run_operation(
        self,
        execution: OperationExecution,
        call: CallToolRequestParams,
        permit: EffectPermit,
    ) -> None:
        try:
            result = await self.exchange(call, permit, long=True)
            async with self.lock:
                if execution.operation.finish(failed=bool(result.is_error)):
                    execution.result = result
        except asyncio.CancelledError:
            raise
        except Exception:
            async with self.lock:
                await self.stop()
                execution.operation.state = OperationState.FAILED
                self.schedule_recovery()

    async def _prepare_child(self) -> None:
        self.child = await spawn_child(self.child_module, self.memory_bytes)
        prepared = await prepare_child(self.child)
        self.catalogue = prepared.catalogue

    async def poll(
        self,
        call: CallToolRequestParams,
        authority: OperationAuthority,
    ) -> CallToolResult:
        command = CancelOperationRequest.model_validate(call.arguments or {})
        record = await self.poll_operation.execute(
            command.handle(),
            authority,
            cancel=call.name == "analysis_cancel",
            now=time.time(),
        )
        return self.outcome(record)

    async def admit(self, authority: OperationAuthority) -> None:
        try:
            await self.admit_execution.execute(authority, time.time())
        except AnalysisPreparing:
            raise NodePreparing from None

    def start(
        self,
        call: CallToolRequestParams,
        authority: OperationAuthority,
        permit: EffectPermit,
    ) -> CallToolResult:
        engine, tool = start_selector(call)
        record = self.inventory.add(authority.request_uuid, authority.identity, engine, tool)
        self.operations = {
            key: execution
            for key, execution in self.operations.items()
            if self.inventory.lookup(key) is not None
        }
        execution = OperationExecution(record)
        self.operations[record.operation_id] = execution
        execution.task = asyncio.create_task(self.run_operation(execution, call, permit))
        return self.outcome(record)

    async def call(
        self,
        call: CallToolRequestParams,
        permit: EffectPermit,
    ) -> CallToolResult:
        async with self.lock:
            authority = operation_authority(permit)
            name = call.name
            if name in {"analysis_poll", "analysis_cancel"}:
                return await self.poll(call, authority)
            self.inventory.require_idle()
            if name == "analysis_start":
                self.inventory.require_new(authority.request_uuid)
            try:
                await self.admit(authority)
                if name == "analysis_start":
                    return self.start(call, authority, permit)
                return await self.exchange(call, permit)
            except BaseException:
                await self.stop()
                self.schedule_recovery()
                raise

    async def close(self) -> None:
        self.closed = True
        if self.watchdog_task:
            self.watchdog_task.cancel()
            with suppress(asyncio.CancelledError):
                await self.watchdog_task
        if self.warming:
            self.warming.cancel()
            with suppress(asyncio.CancelledError, Exception):
                await self.warming
        await self.stop()


def start_selector(call: CallToolRequestParams) -> tuple[Engine, str]:
    if len(json.dumps(call.arguments or {}, allow_nan=False).encode()) > 32000:
        raise ValueError("Exact bounded engine operation required")
    selected = engine_invocation(call)
    if selected.command.tool is None:
        raise ValueError("Exact bounded engine operation required")
    return selected.command.engine, selected.command.tool
