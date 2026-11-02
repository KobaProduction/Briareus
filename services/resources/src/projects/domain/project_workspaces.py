"""A persistent workspace belongs to one project on one currently usable node."""

from dataclasses import dataclass
from uuid import UUID


class WorkspaceRejected(ValueError):
    def __init__(self, detail: str, *, forbidden: bool = False) -> None:
        super().__init__(detail)
        self.forbidden = forbidden


@dataclass(frozen=True)
class WorkspaceActor:
    actor_uuid: UUID
    project_owner_kind: str | None
    project_owner_uuid: str | None


@dataclass(frozen=True)
class WorkspaceNode:
    node_uuid: UUID
    scope: str
    owner_uuid: UUID | None
    enabled: bool
    deleted: bool
    paired: bool

    def require_usable(self, actor: WorkspaceActor) -> None:
        if not self.enabled or self.deleted or not self.paired:
            raise WorkspaceRejected("An enabled paired node is required")
        if self.scope == "personal" and self.owner_uuid != actor.actor_uuid:
            raise WorkspaceRejected("Node must belong to the current project scope", forbidden=True)
        if self.scope == "team" and (
            actor.project_owner_kind != "team" or actor.project_owner_uuid != str(self.owner_uuid)
        ):
            raise WorkspaceRejected("Node must belong to the current project scope", forbidden=True)


@dataclass(frozen=True)
class ProjectWorkspace:
    id: UUID
    node_uuid: UUID
    project_uuid: UUID
    purpose: str
    retention: str

    def require_persistent(self) -> None:
        if self.retention != "persistent":
            raise WorkspaceRejected("Persistent project workspace required")


@dataclass(frozen=True)
class WorkspaceIdentity:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    node_uuid: UUID
    fingerprint: str


@dataclass(frozen=True)
class WorkspaceReplay:
    operation: str
    digest: str
    workspace: ProjectWorkspace

    def require_current(
        self, identity: WorkspaceIdentity, current: ProjectWorkspace | None
    ) -> None:
        if (
            self.digest != identity.fingerprint
            or self.operation != str(identity.operation_uuid)
            or current is None
            or self.workspace != current
        ):
            raise WorkspaceRejected("Current workspace receipt unavailable")
