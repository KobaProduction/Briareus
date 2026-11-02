"""Session lifecycle orchestration over transaction-scoped authority/storage ports."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol
from uuid import UUID, uuid4

from authorization.domain.sessions import (
    ElevationRequest,
    SessionResourceGrant,
    SessionState,
    checked_elevation_seconds,
    checked_grants,
    normal_session,
    require_base_for_resolution,
)


@dataclass(frozen=True, slots=True)
class SessionAudit:
    action: str
    target_uuid: UUID
    approved: bool | None = None


class SessionAuthorityPort(Protocol):
    async def require_access(self, *, for_write: bool, approve: bool = False) -> None: ...


class SessionRepositoryPort(Protocol):
    async def session(self, session_uuid: UUID, *, lock: bool = False) -> SessionState: ...
    async def add_session(self, state: SessionState) -> None: ...
    async def save_session(self, state: SessionState) -> None: ...
    async def approval(self, request_uuid: UUID) -> ElevationRequest: ...
    async def add_approval(self, request: ElevationRequest) -> None: ...
    async def save_approval(self, request: ElevationRequest) -> None: ...
    def audit(self, event: SessionAudit) -> None: ...


class SessionResourceScopePort(Protocol):
    def requested(self, grants: tuple[str, ...]) -> tuple[SessionResourceGrant, ...]: ...
    def approved(
        self,
        request: ElevationRequest,
        grants: tuple[str, ...],
    ) -> tuple[SessionResourceGrant, ...]: ...


class SessionLifecycle:
    def __init__(
        self,
        *,
        repository: SessionRepositoryPort,
        authority: SessionAuthorityPort,
        resources: SessionResourceScopePort,
        actor_uuid: UUID,
        project_uuid: UUID,
    ) -> None:
        self.repository = repository
        self.authority = authority
        self.resources = resources
        self.actor_uuid = actor_uuid
        self.project_uuid = project_uuid

    async def open_normal(self, *, elevation_policy: str, label: str | None) -> SessionState:
        await self.authority.require_access(for_write=True)
        state = normal_session(
            session_uuid=uuid4(),
            project_uuid=self.project_uuid,
            actor_uuid=self.actor_uuid,
            elevation_policy=elevation_policy,
            label=label,
            now=datetime.now(UTC),
        )
        await self.repository.add_session(state)
        self.repository.audit(SessionAudit("session.opened", state.session_uuid))
        return state

    async def validate_operation(self, session_uuid: UUID, operation: str) -> SessionState:
        await self.authority.require_access(for_write=False)
        state = await self.repository.session(session_uuid)
        state.require_project(self.project_uuid)
        state.require_operation(operation, datetime.now(UTC))
        return state

    async def request_elevation(
        self,
        session_uuid: UUID,
        grants: tuple[str, ...],
        *,
        seconds: int,
        expected_grant_revision: int | None = None,
    ) -> UUID:
        await self.authority.require_access(for_write=True)
        state = await self.repository.session(session_uuid, lock=True)
        state.require_project(self.project_uuid)
        # The legacy HTTP operation has no revision field. Its comparison uses
        # the current owner revision under the same write lock, never a default
        # revision manufactured by the transport adapter.
        revision = state.version if expected_grant_revision is None else expected_grant_revision
        state.require_elevation_request(revision, datetime.now(UTC))
        duration = checked_elevation_seconds(seconds)
        approved = checked_grants(grants, allow_privileged=True)
        request = ElevationRequest(
            request_uuid=uuid4(),
            session_uuid=session_uuid,
            project_uuid=self.project_uuid,
            requested_by_user_uuid=self.actor_uuid,
            grants=approved,
            resources=self.resources.requested(approved),
            requested_expires_at=datetime.now(UTC) + duration,
        )
        await self.repository.add_approval(request)
        self.repository.audit(SessionAudit("session.elevation_requested", request.request_uuid))
        return request.request_uuid

    async def resolve_elevation(
        self,
        request_uuid: UUID,
        *,
        approve: bool,
        allowed_grants: tuple[str, ...] | None,
        expected_version: int,
    ) -> SessionState | None:
        await self.authority.require_access(for_write=True, approve=True)
        request = await self.repository.approval(request_uuid)
        request.require_resolution(
            project_uuid=self.project_uuid,
            actor_uuid=self.actor_uuid,
            approve=approve,
            expected_version=expected_version,
        )
        base = await self.repository.session(request.session_uuid, lock=True)
        now = datetime.now(UTC)
        require_base_for_resolution(base, self.project_uuid, now)
        elevated = self._approved_session(request, base, allowed_grants, now) if approve else None
        if elevated is not None:
            await self.repository.add_session(elevated)
        resolved = request.resolved(
            actor_uuid=self.actor_uuid,
            issued_session_uuid=elevated.session_uuid if elevated is not None else None,
            now=now,
        )
        await self.repository.save_approval(resolved)
        self.repository.audit(SessionAudit("session.elevation_resolved", request_uuid, approve))
        return elevated

    def _approved_session(
        self,
        request: ElevationRequest,
        base: SessionState,
        allowed_grants: tuple[str, ...] | None,
        now: datetime,
    ) -> SessionState:
        actual = request.approved_grants(allowed_grants)
        resources = self.resources.approved(request, actual)
        return request.elevated_session(
            base=base,
            session_uuid=uuid4(),
            grants=actual,
            resources=resources,
            now=now,
        )

    async def revoke(self, session_uuid: UUID) -> SessionState:
        await self.authority.require_access(for_write=True, approve=True)
        state = await self.repository.session(session_uuid, lock=True)
        state.require_project(self.project_uuid)
        revoked = state.revoked(datetime.now(UTC))
        if revoked is not state:
            await self.repository.save_session(revoked)
            self.repository.audit(SessionAudit("session.revoked", session_uuid))
        return revoked
