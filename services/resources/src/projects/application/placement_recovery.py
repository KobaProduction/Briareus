"""Commit recovery and its audit atomically; dispatch only after a new commit."""

from contextlib import AbstractAsyncContextManager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from projects.application._transaction_binding import _PlacementActivityBinding
from projects.application.placement_execution import PlacementWriteOutcome
from projects.application.placement_listing import PlacementOperationView
from projects.domain.node_administration import NodeActor, NodeForbidden, NodeMissing
from projects.domain.placement_admission import PlacementMutationState
from projects.domain.placement_reconciliation import ACTIVE_PHASES
from projects.domain.placement_recovery import (
    RecoveryIntent,
    RecoveryReplay,
    require_reconciliation_capacity,
)


class PlacementRecoverySession(Protocol):
    async def lock(
        self, placement_uuid: UUID, project_uuid: UUID
    ) -> PlacementMutationState | None: ...
    async def receipt(self, operation_uuid: UUID) -> RecoveryReplay | None: ...
    async def latest_phase(self, placement_uuid: UUID) -> str | None: ...
    async def stage(self, intent: RecoveryIntent, actor: NodeActor) -> None: ...
    async def resume(self, intent: RecoveryIntent, actor: NodeActor) -> UUID: ...
    async def summary(self, operation_uuid: UUID) -> PlacementOperationView: ...


class PlacementRecoveryTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[PlacementRecoverySession]: ...


class RecoverPlacement(_PlacementActivityBinding[PlacementRecoveryTransactions]):
    async def execute(
        self, intent: RecoveryIntent, actor: NodeActor, expiry: datetime
    ) -> PlacementWriteOutcome:
        dispatch = False
        operation_uuid = intent.operation_uuid
        async with self.transactions.transaction() as session:
            placement = await session.lock(intent.placement_uuid, intent.project_uuid)
            if placement is None:
                raise NodeMissing("Project placement not found")
            existing = await session.receipt(intent.operation_uuid)
            if existing is not None:
                existing.require_matches(intent)
                operation_uuid = existing.resumed_operation or intent.operation_uuid
            else:
                require_reconciliation_capacity(self.active_count())
                placement.require_sequence(intent.expected_sequence, "recovery")
                phase = await session.latest_phase(placement.id)
                if phase in ACTIVE_PHASES | {"unknown"} and placement.state in {
                    "pending",
                    "updating",
                }:
                    operation_uuid = await session.resume(intent, actor)
                else:
                    placement.require_terminal(phase, "recovery")
                    await session.stage(intent, actor)
                dispatch = True
            if expiry <= self.now():
                raise NodeForbidden("Current Platform proof required")
            operation = await session.summary(operation_uuid)
        return PlacementWriteOutcome(operation, dispatch)
