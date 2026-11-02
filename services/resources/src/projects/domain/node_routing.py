"""A route is a short projection of current applied state, never an execution grant."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from projects.domain.node_administration import NodeCapacity
from projects.domain.provider_connections import ConnectionFailure

type RoutedModule = Literal[
    "files", "terminal", "web", "svc", "infrastructure", "reverse", "serena"
]


@dataclass(frozen=True)
class RoutePlacement:
    id: UUID
    node_uuid: UUID
    project_uuid: UUID
    module: str
    storage_uuid: UUID | None
    limits: NodeCapacity


@dataclass(frozen=True)
class RouteNode:
    id: UUID
    enabled: bool
    deleted: bool
    pinned: bool
    approved: bool
    origin: str


@dataclass(frozen=True)
class RouteRelease:
    published: bool
    module: str
    image: str | None


@dataclass(frozen=True)
class RouteArtifact:
    enabled: bool
    storage_purpose: str


@dataclass(frozen=True)
class AppliedRoute:
    node_uuid: UUID
    placement_uuid: UUID
    project_uuid: UUID
    module: str
    image: str
    port: int
    enabled: bool
    fingerprint: str
    accepted_fingerprint: str
    sequence: int
    limits: NodeCapacity
    storage_uuid: UUID | None
    effect_verify_key: str


@dataclass(frozen=True)
class RouteStorage:
    id: UUID
    node_uuid: UUID
    project_uuid: UUID
    purpose: str
    persistent: bool


@dataclass(frozen=True)
class RouteEvidence:
    placement: RoutePlacement
    node: RouteNode | None
    release: RouteRelease | None
    artifact: RouteArtifact | None
    applied: AppliedRoute | None
    storage: RouteStorage | None
    expires_at: int

    def verified(self, project_uuid: UUID, module: RoutedModule) -> "VerifiedRoute":
        node, release, artifact, applied = self.node, self.release, self.artifact, self.applied
        if node is None or release is None or artifact is None or applied is None:
            raise ConnectionFailure(503, "Current node placement unavailable")
        if (
            node.deleted
            or not node.enabled
            or not node.pinned
            or not node.approved
            or not release.published
            or release.module != module
            or not artifact.enabled
        ):
            raise ConnectionFailure(503, "Current node placement unavailable")
        self.require_applied(project_uuid, module, node, release, applied)
        return VerifiedRoute(self.placement, node, artifact, applied, self.storage)

    def require_applied(
        self,
        project_uuid: UUID,
        module: RoutedModule,
        node: RouteNode,
        release: RouteRelease,
        applied: AppliedRoute,
    ) -> None:
        placement = self.placement
        if (
            not applied.enabled
            or applied.node_uuid != node.id
            or node.id != placement.node_uuid
            or applied.placement_uuid != placement.id
            or applied.project_uuid != project_uuid
            or placement.project_uuid != project_uuid
            or placement.module != module
            or applied.module != module
            or applied.image != release.image
            or applied.fingerprint != applied.accepted_fingerprint
            or applied.limits != placement.limits
            or applied.storage_uuid != placement.storage_uuid
        ):
            raise ConnectionFailure(503, "Applied placement proof mismatch")


@dataclass(frozen=True)
class VerifiedRoute:
    placement: RoutePlacement
    node: RouteNode
    artifact: RouteArtifact
    applied: AppliedRoute
    storage: RouteStorage | None

    def workspace(self) -> RouteStorage:
        if self.applied.storage_uuid is None or not self.applied.effect_verify_key:
            raise ConnectionFailure(503, "Approved Files workspace required")
        storage = self.storage
        if (
            storage is None
            or storage.id != self.applied.storage_uuid
            or storage.node_uuid != self.node.id
            or storage.project_uuid != self.placement.project_uuid
            or storage.purpose != self.artifact.storage_purpose
            or not storage.persistent
        ):
            raise ConnectionFailure(503, "Current workspace owner binding required")
        return storage
