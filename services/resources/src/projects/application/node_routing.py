"""Current physical route projection and human scope views over typed owner ports."""

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import UUID

from node_protocol.effect import NodeWorkspaceBinding
from node_protocol.module_effects import resource_id
from node_protocol.routing import NodeRoute
from projects.application._transaction_binding import _PlatformClockBinding
from projects.application.node_administration import PlatformActors
from projects.domain.node_administration import OperatorSelector, current_lease
from projects.domain.node_routing import RoutedModule, RouteEvidence
from projects.domain.provider_connections import ConnectionFailure


class RouteEvidenceSource(Protocol):
    async def read(
        self, project_uuid: UUID, module: RoutedModule, *, workspace: bool
    ) -> RouteEvidence | None: ...


class ProjectNodeProjection:
    def __init__(self, source: RouteEvidenceSource, now: Callable[[], datetime]) -> None:
        self._source, self._now = source, now

    async def execute(
        self,
        project_uuid: UUID,
        module: RoutedModule,
        *,
        workspace: bool,
    ) -> NodeRoute | NodeWorkspaceBinding:
        evidence = await self._source.read(project_uuid, module, workspace=workspace)
        if evidence is None:
            raise ConnectionFailure(503, "No ready project placement")
        verified = evidence.verified(project_uuid, module)
        expiry = evidence.expires_at
        if workspace:
            storage = verified.workspace()
            result: NodeRoute | NodeWorkspaceBinding = NodeWorkspaceBinding(
                node_uuid=verified.node.id,
                placement_uuid=verified.placement.id,
                project_uuid=project_uuid,
                workspace_uuid=storage.id,
                fingerprint=verified.applied.fingerprint,
                effect_verify_key=verified.applied.effect_verify_key,
                expires_at=expiry,
                resource_revision=verified.applied.sequence,
                resource_id=resource_id(module, verified.node.id, project_uuid, storage.id),
            )
        else:
            result = NodeRoute(
                node_uuid=verified.node.id,
                placement_uuid=verified.placement.id,
                project_uuid=project_uuid,
                module=module,
                origin=verified.node.origin,
                fingerprint=verified.applied.fingerprint,
                port=verified.applied.port,
                expires_at=expiry,
            )
        if result.expires_at <= self._now().timestamp():
            raise ConnectionFailure(503, "Route projection expired")
        return result


class AuthorizeHumanScope(_PlatformClockBinding[PlatformActors]):
    async def execute(self, selector: OperatorSelector) -> datetime:
        if not current_lease(selector.identity_expires_at, self._now()):
            raise ConnectionFailure(403, "Current identity required")
        found = await self._platform.read(selector)
        evidence = found.evidence
        if (
            found.status != 200
            or evidence is None
            or evidence.issuer != selector.issuer
            or evidence.subject != selector.subject
            or evidence.actor_uuid != str(selector.actor_uuid)
            or evidence.project_uuid != str(selector.project_uuid)
            or "use_resources" not in evidence.permissions
            or not current_lease(evidence.expires_at, self._now())
        ):
            raise ConnectionFailure(403, "Current project membership required")
        return min(evidence.expires_at, selector.identity_expires_at)
