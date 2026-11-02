"""SQL, platform authority and legacy resource-wire adapters for session use cases."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._project_access import CallerPrincipal, ProjectPermission
from authorization._resource_scope import (
    TrustedResourceOwnerPort,
    matches_current_owner,
)
from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from authorization.application.sessions import SessionAudit
from authorization.domain.resource_scopes import canonical_grants
from authorization.domain.sessions import (
    ElevationRequest,
    InvalidSessionInput,
    SessionAccessDenied,
    SessionResourceGrant,
    SessionState,
)
from authorization.infrastructure.journal_records import ApprovalAudit
from authorization.infrastructure.session_grant_storage import StoredSessionPermissions
from authorization.infrastructure.session_scopes import stored_resources
from authorization.infrastructure.session_state import (
    _SessionStateWriter,
    session_state,
    stored_operations,
)
from common.platform_ids import PlatformProjectId


async def load_session_row(
    tx: AsyncSession,
    session_uuid: UUID,
    *,
    lock: bool = False,
) -> ProjectAgentSessionRow:
    if session_uuid.version != 4:
        raise SessionAccessDenied("SESSION_UUID_INVALID")
    query = select(ProjectAgentSessionRow).where(
        ProjectAgentSessionRow.session_uuid == session_uuid
    )
    if lock:
        query = query.with_for_update().execution_options(populate_existing=True)
    row = await tx.scalar(query)
    if row is None:
        raise SessionAccessDenied("SESSION_UUID_INVALID")
    return row


class SqlSessionRepository(_SessionStateWriter):
    def __init__(
        self,
        tx: AsyncSession,
        application: PlatformApplication,
        caller: CallerPrincipal,
        project_uuid: PlatformProjectId,
    ) -> None:
        self.tx = tx
        self.application = application
        self.caller = caller
        self.project_uuid = project_uuid
        self._sessions = {}
        self._approvals: dict[UUID, SessionApprovalRow] = {}

    async def row(self, session_uuid: UUID, *, lock: bool = False) -> ProjectAgentSessionRow:
        row = await load_session_row(self.tx, session_uuid, lock=lock)
        self._sessions[session_uuid] = row
        return row

    async def session(self, session_uuid: UUID, *, lock: bool = False) -> SessionState:
        return session_state(await self.row(session_uuid, lock=lock))

    async def add_session(self, state: SessionState) -> None:
        row = ProjectAgentSessionRow(
            session_uuid=state.session_uuid,
            project_id=state.project_uuid,
            created_by_principal_id=state.created_by_principal_uuid,
            grants=StoredSessionPermissions(
                state.grants, state.resources if state.is_elevated else ()
            ),
            elevation_policy=state.elevation_policy,
            label=state.label,
            status=state.status,
            is_elevated=state.is_elevated,
            version=state.version,
            created_at=state.created_at,
            hard_expires_at=state.hard_expires_at,
        )
        self.tx.add(row)
        await self.tx.flush()
        self._sessions[state.session_uuid] = row

    async def save_session(self, state: SessionState) -> None:
        self._store_session_state(state)

    async def approval(self, request_uuid: UUID) -> ElevationRequest:
        row = await self.tx.scalar(
            select(SessionApprovalRow)
            .where(SessionApprovalRow.id == request_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise SessionAccessDenied("Project access denied")
        self._approvals[request_uuid] = row
        # Resource scopes are decoded only on approval, preserving rejection of
        # obsolete/malformed requests without requiring a usable grant payload.
        return ElevationRequest(
            request_uuid=row.id,
            session_uuid=row.session_uuid,
            project_uuid=row.project_id,
            requested_by_user_uuid=row.requested_by_user_id,
            grants=stored_operations(row.requested_grants.operations),
            resources=(),
            requested_expires_at=row.requested_expires_at,
            status=row.status,
            version=row.version,
            resolved_by_user_uuid=row.resolved_by_user_id,
            issued_session_uuid=row.issued_session_uuid,
            resolved_at=row.resolved_at,
        )

    def approval_resources(self, request: ElevationRequest) -> tuple[SessionResourceGrant, ...]:
        row = self._approvals[request.request_uuid]
        try:
            return stored_resources(row.requested_grants.resources, request.grants)
        except ValueError as exc:
            raise SessionAccessDenied("stored resource approval scope invalid") from exc

    async def add_approval(self, request: ElevationRequest) -> None:
        row = SessionApprovalRow(
            id=request.request_uuid,
            session_uuid=request.session_uuid,
            project_id=request.project_uuid,
            requested_by_user_id=request.requested_by_user_uuid,
            requested_grants=StoredSessionPermissions(request.grants, request.resources),
            requested_expires_at=request.requested_expires_at,
            status=request.status,
        )
        self.tx.add(row)
        await self.tx.flush()
        self._approvals[request.request_uuid] = row

    async def save_approval(self, request: ElevationRequest) -> None:
        row = self._approvals[request.request_uuid]
        row.status = request.status
        row.version = request.version
        row.resolved_by_user_id = request.resolved_by_user_uuid
        row.issued_session_uuid = request.issued_session_uuid
        row.resolved_at = request.resolved_at

    def audit(self, event: SessionAudit) -> None:
        if event.approved is None:
            self.application._audit(
                self.tx,
                actor=self.caller.user_id,
                project=self.project_uuid,
                action=event.action,
                target=event.target_uuid,
            )
        else:
            self.application._audit(
                self.tx,
                actor=self.caller.user_id,
                project=self.project_uuid,
                action=event.action,
                target=event.target_uuid,
                event=ApprovalAudit(approved=event.approved),
            )


class PlatformSessionAuthority:
    def __init__(
        self,
        tx: AsyncSession,
        application: PlatformApplication,
        caller: CallerPrincipal,
        project_uuid: PlatformProjectId,
    ) -> None:
        self.tx = tx
        self.application = application
        self.caller = caller
        self.project_uuid = project_uuid

    async def require_access(self, *, for_write: bool, approve: bool = False) -> None:
        permission = (
            ProjectPermission.APPROVE_AGENT_SESSION if approve else ProjectPermission.USE_RESOURCES
        )
        await self.application.project_allowed(
            self.tx,
            self.caller,
            self.project_uuid,
            permission,
            for_write=for_write,
        )


class SessionResourceScopes:
    def __init__(
        self,
        repository: SqlSessionRepository,
        owner: TrustedResourceOwnerPort | None,
        requested: tuple[SessionResourceGrant, ...] | None,
    ) -> None:
        self.repository = repository
        self.owner = owner
        self.requested_resources = requested

    def requested(self, grants: tuple[str, ...]) -> tuple[SessionResourceGrant, ...]:
        try:
            return canonical_grants(self.requested_resources or (), set(grants), None)
        except ValueError as exc:
            raise InvalidSessionInput("invalid resource scope request") from exc

    def approved(
        self, request: ElevationRequest, grants: tuple[str, ...]
    ) -> tuple[SessionResourceGrant, ...]:
        resources = tuple(
            scope for scope in self.repository.approval_resources(request) if scope.action in grants
        )
        for scope in resources:
            self._require_current_owner(scope)
        return resources

    def _require_current_owner(self, scope: SessionResourceGrant) -> None:
        if self.owner is None:
            raise SessionAccessDenied("trusted resource owner proof unavailable")
        proof = self.owner.verify_current_scope(
            project_uuid=self.repository.project_uuid, scope=scope
        )
        if not matches_current_owner(proof, project_uuid=self.repository.project_uuid, scope=scope):
            raise SessionAccessDenied("resource is not currently owned by Project")
