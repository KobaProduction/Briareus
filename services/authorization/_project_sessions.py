"""Compatibility composition boundary for project-owned AgentSession operations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from authorization._platform_application import PlatformApplication
from authorization._project_access import CallerPrincipal
from authorization._resource_scope import TrustedResourceOwnerPort
from authorization._session_persistence import ProjectAgentSessionRow
from authorization.application.sessions import SessionLifecycle
from authorization.domain.sessions import ELEVATED_HARD_TTL as ELEVATED_HARD_TTL
from authorization.domain.sessions import NORMAL_TTL as NORMAL_TTL
from authorization.domain.sessions import SAFE_BASIC_GRANTS as SAFE_BASIC_GRANTS
from authorization.domain.sessions import SUPPORTED_GRANTS as SUPPORTED_GRANTS
from authorization.domain.sessions import SessionResourceGrant, SessionState
from authorization.infrastructure.sessions import (
    PlatformSessionAuthority,
    SessionResourceScopes,
    SqlSessionRepository,
    load_session_row,
)
from authorization.presentation.session_errors import session_errors
from common.platform_ids import AgentSessionUuid, PlatformProjectId


@dataclass(frozen=True, slots=True)
class AgentSessionView:
    session_uuid: AgentSessionUuid
    project_id: PlatformProjectId
    grants: tuple[str, ...]
    is_elevated: bool
    hard_expires_at: datetime
    status: str
    version: int
    label: str | None
    elevation_policy: str


def _view(state: SessionState) -> AgentSessionView:
    return AgentSessionView(
        session_uuid=AgentSessionUuid(state.session_uuid),
        project_id=PlatformProjectId(state.project_uuid),
        grants=state.grants,
        is_elevated=state.is_elevated,
        hard_expires_at=state.hard_expires_at,
        status=state.status,
        version=state.version,
        label=state.label,
        elevation_policy=state.elevation_policy,
    )


class ProjectSessionService:
    def __init__(
        self,
        application: PlatformApplication,
        *,
        resource_owner: TrustedResourceOwnerPort | None = None,
    ) -> None:
        self.application = application
        self.resource_owner = resource_owner

    def _lifecycle(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        resource_grants: tuple[SessionResourceGrant, ...] | None = None,
    ) -> SessionLifecycle:
        repository = SqlSessionRepository(session, self.application, caller, project_id)
        return SessionLifecycle(
            repository=repository,
            authority=PlatformSessionAuthority(session, self.application, caller, project_id),
            resources=SessionResourceScopes(repository, self.resource_owner, resource_grants),
            actor_uuid=caller.user_id,
            project_uuid=project_id,
        )

    async def _row(
        self,
        session: AsyncSession,
        session_uuid: AgentSessionUuid,
        *,
        lock: bool = False,
    ) -> ProjectAgentSessionRow:
        # Legacy credential redemption still needs the locked persistence row.
        with session_errors():
            return await load_session_row(session, session_uuid, lock=lock)

    async def open_normal(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        *,
        elevation_policy: str = "requestable",
        label: str | None = None,
    ) -> AgentSessionView:
        with session_errors():
            return _view(
                await self._lifecycle(session, caller, project_id).open_normal(
                    elevation_policy=elevation_policy,
                    label=label,
                )
            )

    async def validate_operation(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
        operation: str,
    ) -> AgentSessionView:
        with session_errors():
            return _view(
                await self._lifecycle(session, caller, project_id).validate_operation(
                    session_uuid,
                    operation,
                )
            )

    async def request_elevation(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
        grants: list[str],
        *,
        seconds: int,
        expected_grant_revision: int | None = None,
        resource_grants: tuple[SessionResourceGrant, ...] | None = None,
    ) -> UUID:
        with session_errors():
            return await self._lifecycle(
                session, caller, project_id, resource_grants
            ).request_elevation(
                session_uuid,
                tuple(grants),
                seconds=seconds,
                expected_grant_revision=expected_grant_revision,
            )

    async def resolve_elevation(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        request_id: UUID,
        *,
        approve: bool,
        allowed_grants: list[str] | None = None,
        explicit_expansion_confirmation: bool = False,
        expected_version: int,
    ) -> AgentSessionView | None:
        # The accepted compatibility keyword never authorizes scope expansion.
        _ = explicit_expansion_confirmation
        with session_errors():
            state = await self._lifecycle(session, caller, project_id).resolve_elevation(
                request_id,
                approve=approve,
                allowed_grants=tuple(allowed_grants) if allowed_grants is not None else None,
                expected_version=expected_version,
            )
            return _view(state) if state is not None else None

    async def revoke(
        self,
        session: AsyncSession,
        caller: CallerPrincipal,
        project_id: PlatformProjectId,
        session_uuid: AgentSessionUuid,
    ) -> AgentSessionView:
        with session_errors():
            return _view(await self._lifecycle(session, caller, project_id).revoke(session_uuid))
