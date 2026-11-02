"""Node admission for placement writes, independent of SQL and HTTP."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from projects.domain.node_administration import NodeActor, NodeConflict, NodeForbidden, NodeInvalid


def placement_name(value: str) -> str:
    name = value.strip()
    if not name:
        raise NodeInvalid("Placement name required")
    return name


@dataclass(frozen=True)
class PlacementMutationState:
    id: UUID
    node_uuid: UUID
    sequence: int
    state: str

    def require_sequence(self, expected: int, operation: Literal["recovery", "updating"]) -> None:
        if self.sequence != expected:
            detail = (
                "Placement changed"
                if operation == "recovery"
                else "Placement changed; select the current state"
            )
            raise NodeConflict(detail)

    def require_terminal(
        self, previous_phase: str | None, operation: Literal["recovery", "updating"]
    ) -> None:
        if previous_phase not in {"succeeded", "failed"} or self.state not in {"ready", "failed"}:
            raise NodeConflict(f"Reconcile the previous operation before {operation}")


@dataclass(frozen=True)
class PlacementNode:
    scope: str
    owner_uuid: UUID | None
    enabled: bool
    deleted: bool
    paired: bool

    def require_available(self) -> None:
        if self.deleted or not self.enabled or not self.paired:
            raise NodeConflict("An enabled paired node is required")

    def require_project_scope(self, actor: NodeActor) -> None:
        # Operator status never allows borrowing another personal or team scope.
        if self.scope == "personal" and self.owner_uuid != actor.actor_uuid:
            raise NodeForbidden("Node must belong to the current project scope")
        if self.scope == "team" and (
            actor.project_owner_kind != "team" or actor.project_owner_uuid != self.owner_uuid
        ):
            raise NodeForbidden("Node must belong to the current project scope")


@dataclass(frozen=True)
class PlacementWorkspace:
    node_uuid: UUID
    project_uuid: UUID
    purpose: str
    retention: str

    def require_project_binding(self, node_uuid: UUID, project_uuid: UUID) -> None:
        if (
            self.node_uuid != node_uuid
            or self.project_uuid != project_uuid
            or self.purpose != "workspace"
            or self.retention != "persistent"
        ):
            raise NodeConflict("Shared workspace must belong to this project and node")
