"""Read project placement views without exposing persistence records to presentation."""

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol
from uuid import UUID

from node_protocol import ResourceLimits, WorkspaceMount
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.models import ModuleConfiguration
from projects.domain.node_administration import NodeForbidden


@dataclass(frozen=True)
class PlacementOperationView:
    id: str
    placement_uuid: str
    sequence: int
    phase: str
    error: str | None
    updated_at: str
    diagnostic: FailureDiagnostic | None
    reconciliation_required: bool | None = None
    restored: bool | None = None


@dataclass(frozen=True)
class PlacementView:
    id: str
    node_uuid: str
    project_uuid: str
    name: str
    module: str
    state: str
    sequence: int
    limits: ResourceLimits
    workspace_uuid: str | None
    release_uuid: str
    configuration: ModuleConfiguration | None
    project_workspace: WorkspaceMount | None
    operation: PlacementOperationView | None
    runtime_policy_pending: bool


class PlacementReader(Protocol):
    async def read(
        self, project_uuid: UUID, node_uuid: UUID | None
    ) -> tuple[PlacementView, ...]: ...


class ReadProjectPlacements:
    def __init__(self, reader: PlacementReader, now: Callable[[], datetime]) -> None:
        self.reader, self.now = reader, now

    async def execute(
        self,
        project_uuid: UUID,
        node_uuid: UUID | None,
        active_operations: frozenset[UUID],
        expiry: datetime,
    ) -> tuple[PlacementView, ...]:
        items = await self.reader.read(project_uuid, node_uuid)
        if expiry <= self.now():
            raise NodeForbidden("Current Platform proof required")
        return tuple(self._activity(item, active_operations) for item in items)

    @staticmethod
    def _activity(item: PlacementView, active: frozenset[UUID]) -> PlacementView:
        operation = item.operation
        if operation is None:
            return item
        activity = replace(
            operation,
            reconciliation_required=(
                operation.phase not in {"succeeded", "failed"} and UUID(operation.id) not in active
            ),
            restored=(
                item.state == "ready"
                and operation.phase == "failed"
                and operation.error == "UPDATE_FAILED"
            ),
        )
        return replace(item, operation=activity)
