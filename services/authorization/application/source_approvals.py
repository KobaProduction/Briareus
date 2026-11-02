"""Signed-owner source approval flow, preserving its distinct authority contract."""

from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from authorization.domain.sessions import (
    ElevationRequest,
    SessionAccessDenied,
    SessionConflict,
    SessionResourceGrant,
    SessionState,
    source_approved_operations,
)
from service_runtime._repository_binding import _RepositoryBinding


class SourceApprovalRepositoryPort(Protocol):
    async def approval(self, approval_uuid: UUID) -> ElevationRequest | None: ...
    async def base(self, session_uuid: UUID) -> SessionState | None: ...
    def requested_operations(self, request: ElevationRequest) -> tuple[str, ...]: ...
    def resources(
        self, request: ElevationRequest, operations: tuple[str, ...]
    ) -> tuple[SessionResourceGrant, ...]: ...
    def require_owners(self, resources: tuple[SessionResourceGrant, ...]) -> None: ...
    def add_session(self, state: SessionState) -> None: ...
    def save_approval(self, request: ElevationRequest) -> None: ...
    def audit(self, target_uuid: UUID) -> None: ...


class ResolveSourceElevation(_RepositoryBinding[SourceApprovalRepositoryPort]):
    async def execute(
        self,
        *,
        actor_uuid: UUID,
        project_uuid: UUID,
        session_uuid: UUID,
        approval_uuid: UUID,
        expected_version: int,
        approve: bool,
        allowed_grants: tuple[str, ...] | None,
    ) -> ElevationRequest:
        request = await self.repository.approval(approval_uuid)
        if (
            request is None
            or request.project_uuid != project_uuid
            or request.session_uuid != session_uuid
        ):
            raise SessionAccessDenied("approval has no signed Project/session ownership")
        if request.version != expected_version or request.status != "pending":
            raise SessionConflict("approval already resolved or revision changed")
        if approve and request.requested_by_user_uuid == actor_uuid:
            raise SessionAccessDenied("an elevation requester cannot approve their own request")
        base = await self.repository.base(session_uuid)
        now = datetime.now(UTC)
        self._require_base(base, project_uuid, now)
        issued: SessionState | None = None
        if approve:
            issued = self._issue(request, base, allowed_grants, now)
        result = request.resolved(
            actor_uuid=actor_uuid,
            issued_session_uuid=issued.session_uuid if issued is not None else None,
            now=now,
        )
        self.repository.save_approval(result)
        self.repository.audit(result.request_uuid)
        return result

    @staticmethod
    def _require_base(base: SessionState | None, project_uuid: UUID, now: datetime) -> None:
        if (
            base is None
            or base.project_uuid != project_uuid
            or base.status != "active"
            or base.hard_expires_at <= now
            or base.elevation_policy != "requestable"
            or base.is_elevated
        ):
            raise SessionAccessDenied("base AgentSession not active or requestable")

    def _issue(
        self,
        request: ElevationRequest,
        base: SessionState | None,
        allowed: tuple[str, ...] | None,
        now: datetime,
    ) -> SessionState:
        if base is None:
            raise SessionAccessDenied("base AgentSession not active or requestable")
        if request.requested_expires_at <= now:
            raise SessionConflict("request elevation lifetime expired")
        operations = source_approved_operations(
            self.repository.requested_operations(request), allowed
        )
        resources = self.repository.resources(request, operations)
        self.repository.require_owners(resources)
        state = request.elevated_session(
            base=base,
            session_uuid=uuid4(),
            grants=operations,
            resources=resources,
            now=now,
        )
        self.repository.add_session(state)
        return state
