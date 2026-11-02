"""Single-writer node reconciler, called only after authenticated Core admission.

No shell, host Docker fallback, all-service restart, volume deletion or automatic
MCP effect retry. The node Gateway closes a placement while its operation runs.
"""

from __future__ import annotations

import asyncio
from uuid import UUID

from node_protocol import Deployment, NodeRecord, ResourceLimits
from node_protocol.diagnostics import FailureDiagnostic

from .application.completion import ObserveCompletion
from .application.inventory import ObserveInventory
from .application.placement import ApplyPlacement, OperationSnapshot, validate_admission
from .application.readiness import ReadinessFailed, WaitReady
from .diagnostics import diagnostic_from_state
from .docker_engine import DockerEngine, EngineFailure
from .domain.inventory import InventoryInvalid
from .infrastructure.completion import ControllerCompletionRuntime, JournalCompletionStore
from .infrastructure.failure_diagnostic import InspectFailure
from .infrastructure.inventory import DockerComponentInventory, egress_quota
from .infrastructure.journal_records import OperationRecord
from .infrastructure.placement import ControllerPlacementRuntime, JournalOperationStore
from .infrastructure.readiness import ControllerReadinessRuntime
from .journal import Journal
from .planner import Instance


class Controller:
    def __init__(self, node: NodeRecord, engine: DockerEngine, journal: Journal) -> None:
        self.node, self.engine, self.journal = node, engine, journal
        # Serializes admission and capacity accounting across placements.
        self.lock = asyncio.Lock()

    async def observed(self) -> list[Instance]:
        inventory = ObserveInventory(DockerComponentInventory(self.engine), egress_quota())
        try:
            placements = await inventory.execute(self.node.id)
        except InventoryInvalid as exc:
            raise EngineFailure(str(exc)) from exc
        return [
            Instance(
                item.container_id,
                item.deployment_uuid,
                item.fingerprint,
                ResourceLimits(
                    memory_bytes=item.allocation.memory_bytes,
                    cpu_millis=item.allocation.cpu_millis,
                    pids=item.allocation.pids,
                ),
                item.running,
                item.ready,
            )
            for item in placements
        ]

    async def wait_ready(self, container: str) -> None:
        try:
            await WaitReady(ControllerReadinessRuntime(self)).execute(container)
        except ReadinessFailed as failure:
            raise EngineFailure(
                "Target failed readiness",
                diagnostic=diagnostic_from_state("checking", failure.state),
            ) from failure

    async def observe_completion(self, operation: UUID, sequence: int) -> OperationRecord | None:
        """Finalize a lost checking receipt from fresh exact native inventory only.

        Called by the signed Core Operation RPC. Never starts, stops, pulls or
        replaces a container and never resumes a user MCP process lease.
        """
        async with self.lock:
            await ObserveCompletion(
                JournalCompletionStore(self.journal), ControllerCompletionRuntime(self)
            ).execute(operation, sequence)
            return await self.journal.get(operation)

    async def apply(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> OperationRecord | None:
        validate_admission(self.node, desired)
        async with self.lock:
            await self.placement_application().execute(operation, sequence, desired)
            return await self.journal.get(operation)

    async def failure_diagnostic(
        self,
        receipt: OperationSnapshot,
        desired: Deployment,
        *,
        deadline_expired: bool = False,
    ) -> FailureDiagnostic:
        return await InspectFailure(self.engine).execute(
            receipt.phase,
            receipt.container,
            desired,
            deadline_expired=deadline_expired,
        )

    async def rollback(
        self, operation: UUID, previous: Deployment | None, desired: Deployment
    ) -> None:
        await self.placement_application().rollback(operation, previous, desired)

    def placement_application(self) -> ApplyPlacement:
        return ApplyPlacement(
            lambda: self.node, JournalOperationStore(self.journal), ControllerPlacementRuntime(self)
        )
