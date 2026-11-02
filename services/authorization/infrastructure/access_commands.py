"""Access SQL owner adapter; locks and audit/outbox remain in one transaction."""

from typing import cast
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_persistence import OutboxRow, SecurityAuditRow
from authorization._resource_scope import (
    TrustedResourceOwnerPort,
    matches_current_owner,
)
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from authorization.application.access_commands import (
    AccessCommandScope,
    ApprovalReference,
    StoredApproval,
)
from authorization.domain.access_commands import valid_operation_request
from authorization.domain.sessions import (
    ElevationRequest,
    SessionAccessDenied,
    SessionResourceGrant,
    SessionState,
)
from authorization.infrastructure.journal_records import AccessMutationEvent
from authorization.infrastructure.session_grant_storage import StoredSessionPermissions
from authorization.infrastructure.session_scopes import stored_resources
from authorization.infrastructure.session_state import (
    _SessionStateWriter,
    session_state,
    stored_operations,
)
from common.infrastructure.audit_records import OperationAudit
from common.platform_ids import PlatformProjectId


class SqlAccessCommandRepository(_SessionStateWriter):
    def __init__(
        self,
        tx: AsyncSession,
        actor_uuid: UUID,
        scope: AccessCommandScope,
        resource_owner: TrustedResourceOwnerPort | None,
    ) -> None:
        self.tx = tx
        self.actor_uuid = actor_uuid
        self.scope = scope
        self.resource_owner = resource_owner
        self._sessions = {}
        self._approvals: dict[UUID, SessionApprovalRow] = {}

    async def session(self, session_uuid: UUID) -> SessionState | None:
        row = await self.tx.scalar(
            select(ProjectAgentSessionRow)
            .where(ProjectAgentSessionRow.session_uuid == session_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        self._sessions[session_uuid] = row
        return session_state(row)

    async def approval_reference(self, approval_uuid: UUID) -> ApprovalReference | None:
        row = await self.tx.scalar(
            select(SessionApprovalRow).where(SessionApprovalRow.id == approval_uuid)
        )
        return ApprovalReference(row.project_id, row.session_uuid) if row is not None else None

    async def approval(self, approval_uuid: UUID) -> StoredApproval | None:
        row = await self.tx.scalar(
            select(SessionApprovalRow)
            .where(SessionApprovalRow.id == approval_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            return None
        self._approvals[approval_uuid] = row
        operations = row.requested_grants.operations
        return StoredApproval(
            ElevationRequest(
                request_uuid=row.id,
                session_uuid=row.session_uuid,
                project_uuid=row.project_id,
                requested_by_user_uuid=row.requested_by_user_id,
                grants=stored_operations(operations),
                resources=(),
                requested_expires_at=row.requested_expires_at,
                status=row.status,
                version=row.version,
            ),
            valid_operation_request(operations),
        )

    def add_session(self, state: SessionState) -> None:
        self.tx.add(
            ProjectAgentSessionRow(
                session_uuid=state.session_uuid,
                project_id=state.project_uuid,
                created_by_principal_id=state.created_by_principal_uuid,
                is_elevated=state.is_elevated,
                elevation_policy=state.elevation_policy,
                label=state.label,
                grants=StoredSessionPermissions(state.grants, state.resources),
                status=state.status,
                version=state.version,
                created_at=state.created_at,
                hard_expires_at=state.hard_expires_at,
            )
        )

    save_session = _SessionStateWriter._store_session_state

    def add_approval(self, request: ElevationRequest) -> None:
        self.tx.add(
            SessionApprovalRow(
                id=request.request_uuid,
                session_uuid=request.session_uuid,
                project_id=request.project_uuid,
                requested_by_user_id=request.requested_by_user_uuid,
                requested_grants=StoredSessionPermissions(request.grants, request.resources),
                requested_expires_at=request.requested_expires_at,
                status=request.status,
                version=request.version,
            )
        )

    def save_approval(self, request: ElevationRequest) -> None:
        row = self._approvals[request.request_uuid]
        row.status = request.status
        row.version = request.version
        row.resolved_by_user_id = request.resolved_by_user_uuid
        row.resolved_at = request.resolved_at
        row.issued_session_uuid = request.issued_session_uuid

    def approval_resources(self, request: ElevationRequest) -> tuple[SessionResourceGrant, ...]:
        row = self._approvals[request.request_uuid]
        try:
            scopes = stored_resources(
                row.requested_grants.resources,
                request.grants,
                project_uuid=self.scope.project_uuid,
            )
        except ValueError:
            raise SessionAccessDenied("stored Resource scope invalid") from None
        return scopes

    def require_current_owner(self, resources: tuple[SessionResourceGrant, ...]) -> None:
        if resources and self.resource_owner is None:
            raise SessionAccessDenied("current Resource owner proof unavailable")
        for scope in resources:
            self._require_owner(scope)

    def _require_owner(self, scope: SessionResourceGrant) -> None:
        if self.resource_owner is None:
            raise SessionAccessDenied("current Resource owner proof unavailable")
        project_uuid = PlatformProjectId(self.scope.project_uuid)
        proof = self.resource_owner.verify_current_scope(project_uuid=project_uuid, scope=scope)
        if not matches_current_owner(proof, project_uuid=project_uuid, scope=scope):
            raise SessionAccessDenied("resource does not belong to current Project")

    async def children(self, parent: SessionState) -> tuple[UUID, ...]:
        rows = await self.tx.scalars(
            select(SessionApprovalRow.issued_session_uuid)
            .where(
                SessionApprovalRow.session_uuid == parent.session_uuid,
                SessionApprovalRow.project_id == parent.project_uuid,
                SessionApprovalRow.issued_session_uuid.is_not(None),
            )
            .with_for_update()
        )
        # SQL excludes NULL; retain unexpected fixture/corruption values so the
        # application rejects them rather than silently skipping a child.
        return cast(tuple[UUID, ...], tuple(rows))

    def audit(self, action: str, target_uuid: UUID) -> None:
        self.tx.add(
            SecurityAuditRow(
                actor_id=self.actor_uuid,
                project_id=self.scope.project_uuid,
                action=action,
                object_id=str(target_uuid),
                details=OperationAudit(operation_uuid=self.scope.operation_uuid),
            )
        )
        self.tx.add(
            OutboxRow(
                event_name=action,
                event_payload=AccessMutationEvent(
                    operation_uuid=self.scope.operation_uuid,
                    project_id=self.scope.project_uuid,
                    entity_id=target_uuid,
                ),
            )
        )
