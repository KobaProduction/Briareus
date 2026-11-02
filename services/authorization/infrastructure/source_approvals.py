"""SQL adapter for the pre-existing signed-owner source approval protocol."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authorization._resource_scope import TrustedResourceOwnerPort, matches_current_owner
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from authorization.application.access_commands import AccessCommandScope
from authorization.domain.sessions import (
    ElevationRequest,
    SessionAccessDenied,
    SessionResourceGrant,
    SessionState,
)
from authorization.infrastructure.access_commands import SqlAccessCommandRepository
from authorization.infrastructure.session_scopes import stored_resources
from authorization.infrastructure.session_state import session_state, stored_operations
from common.platform_ids import PlatformProjectId


class SqlSourceApprovalRepository:
    def __init__(
        self,
        tx: AsyncSession,
        actor_uuid: UUID,
        scope: AccessCommandScope,
        owner: TrustedResourceOwnerPort | None,
    ) -> None:
        self.tx = tx
        self.scope = scope
        self.owner = owner
        self.writer = SqlAccessCommandRepository(tx, actor_uuid, scope, owner)
        self.approvals: dict[UUID, SessionApprovalRow] = {}

    async def approval(self, approval_uuid: UUID) -> ElevationRequest | None:
        row = await self.tx.get(SessionApprovalRow, approval_uuid, with_for_update=True)
        if row is None:
            return None
        self.approvals[approval_uuid] = row
        return ElevationRequest(
            request_uuid=row.id,
            project_uuid=row.project_id,
            session_uuid=row.session_uuid,
            requested_by_user_uuid=row.requested_by_user_id,
            grants=stored_operations(row.requested_grants.operations),
            resources=(),
            requested_expires_at=row.requested_expires_at,
            status=row.status,
            version=row.version,
        )

    async def base(self, session_uuid: UUID) -> SessionState | None:
        row = await self.tx.get(ProjectAgentSessionRow, session_uuid, with_for_update=True)
        return session_state(row) if row is not None else None

    def requested_operations(self, request: ElevationRequest) -> tuple[str, ...]:
        operations = self.approvals[request.request_uuid].requested_grants.operations
        if operations is None:
            raise SessionAccessDenied("invalid stored approval grants")
        return request.grants

    def resources(
        self, request: ElevationRequest, operations: tuple[str, ...]
    ) -> tuple[SessionResourceGrant, ...]:
        try:
            resources = stored_resources(
                self.approvals[request.request_uuid].requested_grants.resources,
                request.grants,
            )
        except ValueError as exc:
            raise SessionAccessDenied("stored scoped resource request invalid") from exc
        return tuple(scope for scope in resources if scope.action in operations)

    def require_owners(self, resources: tuple[SessionResourceGrant, ...]) -> None:
        if resources and self.owner is None:
            raise SessionAccessDenied("trusted resource owner proof unavailable")
        for scope in resources:
            self._require_owner(scope)

    def _require_owner(self, scope: SessionResourceGrant) -> None:
        if self.owner is None:
            raise SessionAccessDenied("trusted resource owner proof unavailable")
        project_uuid = PlatformProjectId(self.scope.project_uuid)
        proof = self.owner.verify_current_scope(project_uuid=project_uuid, scope=scope)
        if not matches_current_owner(proof, project_uuid=project_uuid, scope=scope):
            raise SessionAccessDenied("resource is not currently owned by Project")

    def add_session(self, state: SessionState) -> None:
        self.writer.add_session(state)

    def save_approval(self, request: ElevationRequest) -> None:
        row = self.approvals[request.request_uuid]
        row.status = request.status
        row.version = request.version
        row.resolved_by_user_id = request.resolved_by_user_uuid
        row.resolved_at = request.resolved_at
        if request.issued_session_uuid is not None:
            row.issued_session_uuid = request.issued_session_uuid

    def audit(self, target_uuid: UUID) -> None:
        self.writer.audit("session.elevation_resolved", target_uuid)
