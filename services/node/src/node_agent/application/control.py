"""Core-admitted node configuration, inventory, operation polling and scheduling."""

import asyncio
from typing import Protocol
from uuid import UUID

from node_agent.application.placement import RuntimeFailure
from node_agent.domain.placement import OperationConflict
from node_agent.planner import Instance
from node_protocol import Deployment, NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.domain.observations import (
    NodeConfiguration,
    NodeInventory,
    ObservedLimits,
    ObservedModule,
)
from node_protocol.journal import JournalConfiguration, JournalOperation

from .control_results import (
    ControlResult,
    operation_payload,
    reject,
)


class ControlRuntime(Protocol):
    @property
    def lock(self) -> asyncio.Lock: ...

    def node(self) -> NodeRecord: ...

    def configure(self, record: NodeRecord) -> None: ...

    def validate_budget(self, record: NodeRecord, provisioned: NodeRecord) -> None: ...

    async def verify_rootless(self) -> None: ...

    async def observed(self) -> list[Instance]: ...

    async def observe_completion(
        self, operation: UUID, sequence: int
    ) -> JournalOperation | None: ...


class ControlJournal(Protocol):
    async def configuration(self) -> JournalConfiguration | None: ...

    async def configure(self, sequence: int, record: NodeRecord) -> None: ...

    async def get(self, operation: UUID) -> JournalOperation | None: ...

    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> JournalOperation: ...

    async def event_cursor(self) -> int: ...

    async def phase(self, operation: UUID, phase: str, *, error: str | None = None) -> None: ...


class OperationScheduler(Protocol):
    def draining(self) -> bool: ...

    def active(self, operation: UUID) -> bool: ...

    def full(self) -> bool: ...

    def schedule(self, command: ControlCommand) -> None: ...

    def watch_lease(self) -> None: ...


class NodeControl:
    def __init__(
        self,
        provisioned: NodeRecord,
        runtime: ControlRuntime,
        journal: ControlJournal,
        scheduler: OperationScheduler,
    ) -> None:
        self._provisioned, self._runtime = provisioned, runtime
        self._journal, self._scheduler = journal, scheduler
        self._initialized = False
        self._initializing = asyncio.Lock()
        self._admission = asyncio.Lock()

    async def initialize(self) -> None:
        async with self._initializing:
            if self._initialized:
                return
            cached = await self._journal.configuration()
            if cached is not None:
                restored = cached.record
                if restored.budget != self._provisioned.budget:
                    self._runtime.validate_budget(restored, self._provisioned)
                if (
                    restored.id != self._provisioned.id
                    or restored.scope != self._provisioned.scope
                    or restored.created_at != self._provisioned.created_at
                ):
                    raise ValueError("Stored enrollment conflicts with bootstrap configuration")
                self._runtime.configure(restored)
            self._scheduler.watch_lease()
            self._initialized = True

    async def execute(self, command: ControlCommand) -> ControlResult:
        await self.initialize()
        if self._scheduler.draining():
            return reject(503, "NODE_DRAINING")
        if command.action == "configure":
            return await self._configure(command)
        if command.action == "inventory":
            return await self._inventory()
        if command.action == "status":
            return await self._status(command)
        if command.action != "apply":
            raise ValueError("Control watch uses the event streaming boundary")
        return await self._apply(command)

    async def _configure(self, command: ControlCommand) -> ControlResult:
        record = command.node_record
        if record is None:
            raise ValueError("Configuration record required")
        if (
            record.scope != self._provisioned.scope
            or record.created_at != self._provisioned.created_at
        ):
            return reject(409, "NODE_BOOTSTRAP_CONFIGURATION_MISMATCH")
        async with self._runtime.lock:
            try:
                if record.budget != self._runtime.node().budget:
                    self._runtime.validate_budget(record, self._provisioned)
                    await self._runtime.verify_rootless()
                    allocations = [item.limits for item in await self._runtime.observed()]
                    if not record.budget.fits(allocations):
                        return reject(409, "NODE_BUDGET_BELOW_ALLOCATIONS")
                await self._journal.configure(command.sequence, record)
            except OperationConflict:
                return reject(409, "NODE_CONFIGURATION_CONFLICT")
            except ValueError:
                return reject(409, "NODE_PROVISIONED_CAPACITY_EXCEEDED")
            except RuntimeFailure:
                return reject(503, "NODE_RUNTIME_UNAVAILABLE")
            self._runtime.configure(record)
        return ControlResult(
            200,
            NodeConfiguration(
                node_uuid=self._provisioned.id,
                sequence=command.sequence,
                enabled=record.enabled,
            ),
        )

    async def _inventory(self) -> ControlResult:
        try:
            await self._runtime.verify_rootless()
            observed = await self._runtime.observed()
        except (RuntimeFailure, OSError):
            return reject(503, "NODE_RUNTIME_UNAVAILABLE")
        configuration = await self._journal.configuration()
        return ControlResult(
            200,
            NodeInventory(
                node_uuid=self._provisioned.id,
                enabled=self._runtime.node().enabled,
                event_cursor=await self._journal.event_cursor(),
                sequence=configuration.sequence if configuration else 0,
                items=tuple(
                    ObservedModule(
                        placement_uuid=item.deployment_uuid,
                        fingerprint=item.fingerprint,
                        running=item.running,
                        ready=item.ready,
                        limits=ObservedLimits(
                            item.limits.memory_bytes, item.limits.cpu_millis, item.limits.pids
                        ),
                    )
                    for item in observed
                ),
            ),
        )

    async def _status(self, command: ControlCommand) -> ControlResult:
        current = await self._journal.get(command.operation_uuid)
        if current is None:
            return reject(404, "NODE_OPERATION_NOT_FOUND")
        if current.sequence != command.sequence:
            return reject(409, "NODE_OPERATION_CONFLICT")
        if current.phase == "queued":
            current = await self._interrupt_unstarted(command.operation_uuid)
            if current is None:
                return reject(404, "NODE_OPERATION_NOT_FOUND")
        if current.phase == "checking" and not self._scheduler.active(command.operation_uuid):
            try:
                current = await self._runtime.observe_completion(
                    command.operation_uuid, command.sequence
                )
            except (RuntimeFailure, ValueError):
                return reject(503, "NODE_RUNTIME_UNAVAILABLE")
            if current is None:
                return reject(404, "NODE_OPERATION_NOT_FOUND")
        return ControlResult(200, operation_payload(current))

    async def _interrupt_unstarted(self, operation: UUID) -> JournalOperation | None:
        async with self._admission:
            current = await self._journal.get(operation)
            if (
                current is not None
                and current.phase == "queued"
                and not self._scheduler.active(operation)
            ):
                await self._journal.phase(operation, "failed", error="CONTROLLER_INTERRUPTED")
                return await self._journal.get(operation)
            return current

    async def _apply(self, command: ControlCommand) -> ControlResult:
        async with self._admission:
            return await self._admit(command)

    async def _admit(self, command: ControlCommand) -> ControlResult:
        desired = command.deployment
        if desired is None:
            raise ValueError("Deployment required")
        if not self._runtime.node().enabled or not desired.enabled:
            return reject(403, "NODE_ADMISSION_DISABLED")
        try:
            current = await self._journal.reserve(command.operation_uuid, command.sequence, desired)
        except OperationConflict:
            return reject(409, "NODE_OPERATION_CONFLICT")
        if current.phase not in {"succeeded", "failed"} and not self._scheduler.active(
            command.operation_uuid
        ):
            if self._scheduler.full():
                return reject(429, "NODE_OPERATION_QUEUE_FULL")
            self._scheduler.schedule(command)
        return ControlResult(202, operation_payload(current))
