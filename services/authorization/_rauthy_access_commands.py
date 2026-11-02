"""Rauthy-only, Access-owned AgentSession request/approval/revoke commands.

This is the NEW greenfield command path. It does not require an obsolete
Identity database, legacy owner JWT, a second User password, or cross-owner
SQL. Trusted current Rauthy+Platform+service-peer evidence is injected and
checked again before *every* Access SQL operation and idempotent replay.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from authorization._idempotency import CommandOutcome, IdempotentCommandExecutor
from authorization._resource_scope import (
    TrustedResourceOwnerPort,
)
from authorization.application.access_commands import (
    AccessCommandScope,
    AccessSessionCommands,
    OpenSession,
    RequestElevation,
    ResolveElevation,
)
from authorization.application.access_inputs import (
    AccessCommand as _AccessCommand,
)
from authorization.application.access_inputs import (
    OpenSessionCommand as OpenSessionCommand,
)
from authorization.application.access_inputs import (
    RequestElevationCommand as RequestElevationCommand,
)
from authorization.application.access_inputs import (
    ResolveElevationCommand as ResolveElevationCommand,
)
from authorization.application.access_inputs import (
    RevokeSessionCommand as RevokeSessionCommand,
)
from authorization.application.access_inputs import (
    ScopeEffect as ScopeEffect,
)
from authorization.application.access_inputs import (
    ScopeResource as ScopeResource,
)
from authorization.application.session_receipts import (
    ElevationResponse,
    OpenSessionResponse,
    RevokeSessionResponse,
)
from authorization.domain.access_commands import (
    VerifiedAccessCommandActor as VerifiedAccessCommandActor,
)
from authorization.infrastructure.access_commands import SqlAccessCommandRepository
from authorization.presentation.access_commands import (
    elevation_response,
    open_response,
    revoke_response,
)
from authorization.presentation.session_errors import session_errors
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied


class TrustedAccessCommandAttestor(Protocol):
    async def verify(
        self,
        request: object,
        command: _AccessCommand,
        action: str,
    ) -> VerifiedAccessCommandActor: ...


class AccessRauthyCommandService:
    def __init__(
        self,
        *,
        database: PlatformDatabase,
        idempotency: IdempotentCommandExecutor,
        attestor: TrustedAccessCommandAttestor,
        resource_owner: TrustedResourceOwnerPort | None = None,
    ) -> None:
        if (
            database.engine.url.database != "briareus_access"
            or idempotency.database is not database
            or attestor is None
        ):
            raise ValueError("Authorization commands need one trusted Access owner and attestor")
        self._db = database
        self._idempotency = idempotency
        self._attestor = attestor
        self._resource_owner = resource_owner

    @staticmethod
    def _active_proof(
        verified: VerifiedAccessCommandActor,
        *,
        command: _AccessCommand,
        action: str,
        elevated: bool,
    ) -> None:
        if not isinstance(verified, VerifiedAccessCommandActor):
            raise AccessDenied("current signed Rauthy/Platform operator scope required")
        with session_errors():
            verified.require_active(
                project_uuid=command.project_uuid,
                operation_uuid=command.operation_uuid,
                action=action,
                elevated=elevated,
                now=datetime.now(UTC),
            )

    async def _caller(
        self,
        request: object,
        command: _AccessCommand,
        action: str,
        *,
        elevated: bool,
    ) -> VerifiedAccessCommandActor:
        try:
            verified = await self._attestor.verify(request, command, action)
        except Exception:
            raise AccessDenied("trusted peer/Platform User unavailable") from None
        self._active_proof(verified, command=command, action=action, elevated=elevated)
        return verified

    def _commands(
        self,
        tx: AsyncSession,
        actor: VerifiedAccessCommandActor,
        command: _AccessCommand,
        action: str,
        *,
        elevated: bool,
    ) -> AccessSessionCommands:
        scope = AccessCommandScope(command.project_uuid, command.operation_uuid, action, elevated)
        return AccessSessionCommands(
            SqlAccessCommandRepository(tx, actor.actor_uuid, scope, self._resource_owner),
            actor,
            scope,
        )

    async def open_normal(
        self, request: object, command: OpenSessionCommand
    ) -> CommandOutcome[OpenSessionResponse]:
        action = "session.open"
        actor = await self._caller(request, command, action, elevated=False)

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=False)

        async def perform(tx: AsyncSession) -> CommandOutcome[OpenSessionResponse]:
            with session_errors():
                state = await self._commands(
                    tx, actor, command, action, elevated=False
                ).open_normal(
                    OpenSession(command.elevation_policy, command.label),
                )
                return CommandOutcome(201, open_response(state))

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            request=command,
            fingerprint_mode="json",
            command=perform,
            reauthorize=reauthorize,
            response_model=OpenSessionResponse,
        )

    async def request_elevation(
        self, request: object, command: RequestElevationCommand
    ) -> CommandOutcome[ElevationResponse]:
        action = "session.request_elevation"
        actor = await self._caller(request, command, action, elevated=False)
        normalized = command.resource_grants()
        use_case_command = RequestElevation(
            command.agent_session_uuid,
            command.expected_grant_revision,
            command.operations,
            normalized,
            command.seconds,
        )

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=False)

        async def perform(tx: AsyncSession) -> CommandOutcome[ElevationResponse]:
            with session_errors():
                result = await self._commands(
                    tx, actor, command, action, elevated=False
                ).request_elevation(use_case_command)
                return CommandOutcome(202, elevation_response(result))

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            request=command,
            fingerprint_mode="json",
            command=perform,
            reauthorize=reauthorize,
            response_model=ElevationResponse,
        )

    async def resolve_elevation(
        self, request: object, command: ResolveElevationCommand
    ) -> CommandOutcome[ElevationResponse]:
        action = "session.resolve_elevation"
        actor = await self._caller(request, command, action, elevated=True)
        use_case_command = ResolveElevation(
            command.approval_uuid,
            command.expected_approval_version,
            command.approve,
            command.allowed_operations,
        )

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=True)

        async def perform(tx: AsyncSession) -> CommandOutcome[ElevationResponse]:
            with session_errors():
                result = await self._commands(
                    tx, actor, command, action, elevated=True
                ).resolve_elevation(use_case_command)
                return CommandOutcome(200, elevation_response(result))

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            request=command,
            fingerprint_mode="json",
            command=perform,
            reauthorize=reauthorize,
            response_model=ElevationResponse,
        )

    async def revoke_session(
        self, request: object, command: RevokeSessionCommand
    ) -> CommandOutcome[RevokeSessionResponse]:
        action = "session.revoke"
        actor = await self._caller(request, command, action, elevated=True)

        async def reauthorize(_tx: AsyncSession) -> None:
            self._active_proof(actor, command=command, action=action, elevated=True)

        async def perform(tx: AsyncSession) -> CommandOutcome[RevokeSessionResponse]:
            with session_errors():
                result = await self._commands(
                    tx, actor, command, action, elevated=True
                ).revoke_session(
                    command.agent_session_uuid,
                    command.expected_grant_revision,
                )
                return CommandOutcome(200, revoke_response(result))

        return await self._idempotency.execute(
            actor_scope=str(actor.actor_uuid),
            project_scope=str(command.project_uuid),
            operation=action,
            key=str(command.operation_uuid),
            request=command,
            fingerprint_mode="json",
            command=perform,
            reauthorize=reauthorize,
            response_model=RevokeSessionResponse,
        )
