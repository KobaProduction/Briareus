"""Commit an update once, preserving current authority and exact retry selectors."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from node_protocol import Deployment, ModuleRelease, WorkspaceMount
from node_protocol.management import PlacementUpdate
from node_protocol.models import ModuleConfiguration
from projects.application._transaction_binding import _PlacementActivityBinding
from projects.application.placement_execution import PlacementWriteOutcome
from projects.application.placement_listing import PlacementOperationView
from projects.domain.module_catalog import ResourceLimits as ProfileLimits
from projects.domain.node_administration import (
    NodeActor,
    NodeConflict,
    NodeForbidden,
    NodeInvalid,
    NodeMissing,
)
from projects.domain.placement_admission import PlacementMutationState
from projects.domain.placement_recovery import require_reconciliation_capacity
from projects.domain.placement_update import UpdateIntent, UpdateReplay, UpdateReplayFields


@dataclass(frozen=True)
class PreparedPlacementUpdate:
    current: Deployment
    release: ModuleRelease
    configuration: ModuleConfiguration | None
    project_workspace: WorkspaceMount | None
    minimum_limits: ProfileLimits

    def desired(self, change: PlacementUpdate, previous_phase: str | None) -> Deployment:
        spec = self.current
        limits = change.limits if change.limits is not None else spec.limits
        requested = ProfileLimits(limits.memory_bytes, limits.cpu_millis, limits.pids)
        if not requested.covers(self.minimum_limits):
            raise NodeInvalid("Module limits must include its complete execution profile")
        if (
            spec.release.image == self.release.image
            and self.configuration == spec.configuration
            and limits == spec.limits
            and self.project_workspace == spec.project_workspace
            and previous_phase == "succeeded"
        ):
            raise NodeConflict("This image is already deployed")
        # Revalidate the complete contract; model_copy alone would skip the
        # deployment fingerprint and cross-field validation of a changed intent.
        return Deployment.model_validate(
            {
                **spec.model_dump(mode="json"),
                "release": self.release.model_dump(mode="json"),
                "configuration": self.configuration.model_dump(mode="json")
                if self.configuration is not None
                else None,
                "project_workspace": self.project_workspace.model_dump(mode="json")
                if self.project_workspace is not None
                else None,
                "limits": limits.model_dump(mode="json"),
            }
        )


class PlacementUpdateSession(Protocol):
    async def receipt(self, operation_uuid: UUID) -> UpdateReplay | None: ...
    async def lock(
        self, placement_uuid: UUID, project_uuid: UUID
    ) -> PlacementMutationState | None: ...
    async def replay_fields(self, change: PlacementUpdate) -> UpdateReplayFields: ...
    async def latest_phase(self, placement_uuid: UUID) -> str | None: ...
    async def prepare(
        self, change: PlacementUpdate, actor: NodeActor
    ) -> PreparedPlacementUpdate: ...
    async def stage(
        self, intent: UpdateIntent, previous: Deployment, desired: Deployment
    ) -> None: ...
    async def summary(self, operation_uuid: UUID) -> PlacementOperationView: ...


class PlacementUpdateTransactions(Protocol):
    def transaction(self) -> AbstractAsyncContextManager[PlacementUpdateSession]: ...


class UpdatePlacement(_PlacementActivityBinding[PlacementUpdateTransactions]):
    async def execute(
        self, intent: UpdateIntent, change: PlacementUpdate, actor: NodeActor, expiry: datetime
    ) -> PlacementWriteOutcome:
        dispatch = False
        async with self.transactions.transaction() as session:
            existing = await session.receipt(intent.operation_uuid)
            placement = await session.lock(intent.placement_uuid, intent.project_uuid)
            if placement is None:
                raise NodeMissing("Project placement not found")
            if existing is not None:
                existing.require_matches(intent, await session.replay_fields(change))
            else:
                require_reconciliation_capacity(self.active_count())
                placement.require_sequence(intent.expected_sequence, "updating")
                phase = await session.latest_phase(placement.id)
                placement.require_terminal(phase, "updating")
                prepared = await session.prepare(change, actor)
                await session.stage(intent, prepared.current, prepared.desired(change, phase))
                dispatch = True
            operation = await session.summary(intent.operation_uuid)
            if expiry <= self.now():
                raise NodeForbidden("Current Platform proof required")
        return PlacementWriteOutcome(operation, dispatch)
