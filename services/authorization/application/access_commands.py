"""Owner command use cases; the outer executor owns their one SQL transaction."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID, uuid4

from authorization.domain.access_commands import (
    VerifiedAccessCommandActor,
    allowed_resolution_operations,
    require_child_session,
    require_live_resolution,
    require_requestable_session,
    require_revocable_session,
)
from authorization.domain.session_reads import uuid_v4
from authorization.domain.sessions import (
    ElevationRequest,
    SessionAccessDenied,
    SessionConflict,
    SessionResourceGrant,
    SessionState,
    normal_session,
)


@dataclass(frozen=True, slots=True)
class AccessCommandScope:
    project_uuid: UUID
    operation_uuid: UUID
    action: str
    elevated: bool


@dataclass(frozen=True, slots=True)
class OpenSession:
    elevation_policy: str
    label: str | None


@dataclass(frozen=True, slots=True)
class RequestElevation:
    session_uuid: UUID
    expected_revision: int
    operations: tuple[str, ...]
    resources: tuple[SessionResourceGrant, ...]
    seconds: int


@dataclass(frozen=True, slots=True)
class ResolveElevation:
    approval_uuid: UUID
    expected_version: int
    approve: bool
    allowed_operations: tuple[str, ...] | None


@dataclass(frozen=True, slots=True)
class ApprovalReference:
    project_uuid: UUID
    session_uuid: UUID


@dataclass(frozen=True, slots=True)
class StoredApproval:
    request: ElevationRequest
    valid_operations: bool


class AccessCommandRepositoryPort(Protocol):
    async def session(self, session_uuid: UUID) -> SessionState | None: ...
    async def approval_reference(self, approval_uuid: UUID) -> ApprovalReference | None: ...
    async def approval(self, approval_uuid: UUID) -> StoredApproval | None: ...
    def add_session(self, state: SessionState) -> None: ...
    def save_session(self, state: SessionState) -> None: ...
    def add_approval(self, request: ElevationRequest) -> None: ...
    def save_approval(self, request: ElevationRequest) -> None: ...
    def approval_resources(self, request: ElevationRequest) -> tuple[SessionResourceGrant, ...]: ...
    def require_current_owner(self, resources: tuple[SessionResourceGrant, ...]) -> None: ...
    async def children(self, parent: SessionState) -> tuple[UUID, ...]: ...
    def audit(self, action: str, target_uuid: UUID) -> None: ...


class AccessSessionCommands:
    def __init__(
        self,
        repository: AccessCommandRepositoryPort,
        actor: VerifiedAccessCommandActor,
        scope: AccessCommandScope,
    ) -> None:
        self.repository = repository
        self.actor = actor
        self.scope = scope

    def reauthorize(self) -> None:
        self.actor.require_active(
            project_uuid=self.scope.project_uuid,
            operation_uuid=self.scope.operation_uuid,
            action=self.scope.action,
            elevated=self.scope.elevated,
            now=datetime.now(UTC),
        )

    async def open_normal(self, command: OpenSession) -> SessionState:
        self.reauthorize()
        state = normal_session(
            session_uuid=uuid4(),
            project_uuid=self.scope.project_uuid,
            actor_uuid=self.actor.actor_uuid,
            elevation_policy=command.elevation_policy,
            label=command.label,
            now=datetime.now(UTC),
        )
        self.repository.add_session(state)
        self.repository.audit("session.opened", state.session_uuid)
        return state

    async def request_elevation(self, command: RequestElevation) -> ElevationRequest:
        state = await self.repository.session(command.session_uuid)
        self.reauthorize()
        now = datetime.now(UTC)
        if state is None or state.project_uuid != self.scope.project_uuid:
            raise SessionAccessDenied("unknown Project AgentSession")
        require_requestable_session(state, self.actor.actor_uuid, command.expected_revision, now)
        request = ElevationRequest(
            request_uuid=self.scope.operation_uuid,
            session_uuid=state.session_uuid,
            project_uuid=state.project_uuid,
            requested_by_user_uuid=self.actor.actor_uuid,
            grants=tuple(sorted(command.operations)),
            resources=command.resources,
            requested_expires_at=now + timedelta(seconds=command.seconds),
        )
        self.repository.add_approval(request)
        self.repository.audit("session.elevation_requested", request.request_uuid)
        return request

    async def _resolution_state(
        self, command: ResolveElevation
    ) -> tuple[StoredApproval, SessionState | None]:
        initial = await self.repository.approval_reference(command.approval_uuid)
        if initial is None or initial.project_uuid != self.scope.project_uuid:
            raise SessionAccessDenied("approval Project mismatch")
        # Resolve and transitive revoke share base -> approval -> child lock order.
        base = await self.repository.session(initial.session_uuid)
        stored = await self.repository.approval(command.approval_uuid)
        self.reauthorize()
        if (
            stored is None
            or stored.request.project_uuid != self.scope.project_uuid
            or stored.request.session_uuid != initial.session_uuid
        ):
            raise SessionAccessDenied("approval Project/AgentSession changed")
        return stored, base

    async def resolve_elevation(self, command: ResolveElevation) -> ElevationRequest:
        stored, base = await self._resolution_state(command)
        request = stored.request
        now = datetime.now(UTC)
        require_live_resolution(
            request,
            base,
            actor_uuid=self.actor.actor_uuid,
            project_uuid=self.scope.project_uuid,
            expected_version=command.expected_version,
            approve=command.approve,
            now=now,
        )
        allowed = allowed_resolution_operations(
            request.grants,
            valid_stored_operations=stored.valid_operations,
            allowed=command.allowed_operations,
            approve=command.approve,
        )
        scopes = self.repository.approval_resources(request)
        issued = (
            self._issue_session(request, base, allowed, scopes, now) if command.approve else None
        )
        resolved = replace(
            request.resolved(
                actor_uuid=self.actor.actor_uuid,
                issued_session_uuid=issued.session_uuid if issued is not None else None,
                now=now,
            ),
            resources=scopes,
        )
        self.repository.save_approval(resolved)
        self.repository.audit("session.elevation_resolved", request.request_uuid)
        return resolved

    def _issue_session(
        self,
        request: ElevationRequest,
        base: SessionState | None,
        allowed: tuple[str, ...],
        scopes: tuple[SessionResourceGrant, ...],
        now: datetime,
    ) -> SessionState:
        if base is None:
            raise SessionAccessDenied("base AgentSession no longer eligible")
        granted = tuple(scope for scope in scopes if scope.action in allowed)
        if {scope.action for scope in granted} != set(allowed):
            raise SessionAccessDenied("every approved effect requires an owned resource scope")
        self.repository.require_current_owner(granted)
        expiry = min(
            request.requested_expires_at, base.hard_expires_at, now + timedelta(seconds=300)
        )
        if expiry <= now:
            raise SessionConflict("approval TTL exhausted")
        state = SessionState(
            session_uuid=uuid4(),
            project_uuid=base.project_uuid,
            created_by_principal_uuid=request.requested_by_user_uuid,
            is_elevated=True,
            elevation_policy="fixed",
            label=base.label,
            grants=allowed,
            resources=granted,
            status="active",
            version=1,
            created_at=now,
            hard_expires_at=expiry,
        )
        self.repository.add_session(state)
        return state

    async def _revoke_children(self, state: SessionState, now: datetime) -> None:
        children = await self.repository.children(state)
        if len(set(children)) != len(children):
            raise SessionAccessDenied("duplicate elevated AgentSession reference")
        for child_uuid in children:
            if not uuid_v4(child_uuid):
                raise SessionAccessDenied("invalid elevated AgentSession reference")
            child = require_child_session(await self.repository.session(child_uuid), state)
            self.reauthorize()
            if child.status == "active":
                self.repository.save_session(child.revoked(now))
                self.repository.audit("session.revoked_by_parent", child.session_uuid)
            elif child.status != "revoked":
                raise SessionAccessDenied("elevated session state cannot be safely revoked")

    async def revoke_session(self, session_uuid: UUID, expected_revision: int) -> SessionState:
        state = await self.repository.session(session_uuid)
        self.reauthorize()
        if state is None or state.project_uuid != self.scope.project_uuid:
            raise SessionAccessDenied("unknown Project AgentSession")
        require_revocable_session(state, expected_revision)
        now = datetime.now(UTC)
        if not state.is_elevated:
            await self._revoke_children(state, now)
        self.reauthorize()
        revoked = state.revoked(now)
        self.repository.save_session(revoked)
        self.repository.audit("session.revoked", state.session_uuid)
        return revoked
