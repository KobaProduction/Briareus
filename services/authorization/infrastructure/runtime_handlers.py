"""Adapt independent Platform peers and existing Access command/read boundaries."""

from __future__ import annotations

from dataclasses import dataclass

from fastapi import Request
from sqlalchemy import select

from authorization._approval_read_api import (
    ApprovalListCommand,
    ApprovalListReader,
    SessionGetCommand,
)
from authorization._idempotency import IdempotentCommandExecutor
from authorization._rauthy_access_commands import (
    AccessRauthyCommandService,
    OpenSessionCommand,
    RequestElevationCommand,
    ResolveElevationCommand,
    RevokeSessionCommand,
)
from authorization._runtime_resource_owners import CurrentRuntimeResourceOwners
from authorization._session_persistence import SessionApprovalRow
from authorization.application.event_receipts import EventPageResponse as RuntimeEvents
from authorization.application.runtime_dispatch import (
    RuntimeAction,
    RuntimeApprovals,
    RuntimeSessions,
    RuntimeWriteReceipt,
)
from authorization.application.runtime_inputs import RuntimeEventQuery, RuntimeWriteCommand
from authorization.domain.action_audiences import HAND_EFFECT_AUDIENCES
from authorization.domain.resource_scopes import canonical_grants
from authorization.domain.runtime_policy import RuntimeActor, RuntimeIdentity
from authorization.domain.sessions import SessionResourceGrant
from authorization.presentation.runtime_attestor import HumanAttestor, VerifiedHumanRequest
from authorization.presentation.runtime_protocol import ActorContext
from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied, InvalidInput
from runtime_peer import PeerClient
from runtime_peer.response_decoding import successful_reply


@dataclass(frozen=True, slots=True)
class RuntimeServices:
    database: PlatformDatabase
    commands: AccessRauthyCommandService
    reader: ApprovalListReader
    attestor: HumanAttestor
    encryption_key: str


@dataclass(frozen=True, slots=True)
class RuntimePeers:
    platform: PeerClient
    terminal: PeerClient | None
    files: PeerClient | None
    web: PeerClient | None
    node_resources: PeerClient | None


class PlatformRuntimeActor:
    def __init__(self, platform: PeerClient) -> None:
        self._platform = platform

    async def resolve(self, identity: RuntimeIdentity) -> RuntimeActor:
        _owner_reply = await self._platform.call(
            "/internal/v1/platform/oidc/actor-context",
            {
                "issuer": identity.issuer,
                "subject": identity.subject,
                "project_uuid": str(identity.project_uuid),
            },
            decode=successful_reply(ActorContext.model_validate),
        )
        status, raw_actor = _owner_reply.status, _owner_reply.body
        if status != 200 or raw_actor is None:
            raise AccessDenied("Current Platform actor unavailable")
        actor = raw_actor
        return RuntimeActor(
            actor.issuer,
            actor.subject,
            actor.actor_uuid,
            actor.project_uuid,
            actor.expires_at,
            actor.permissions,
            actor.role,
        )


class RuntimeSessionHandlers:
    def __init__(self, request: Request, services: RuntimeServices, peers: RuntimePeers) -> None:
        self._request = request
        self._services = services
        self._peers = peers

    def _bind(self, actor: RuntimeActor, action: str) -> None:
        self._request.scope["briareus.verified_human_request"] = VerifiedHumanRequest(actor, action)

    async def sessions(
        self,
        actor: RuntimeActor,
        command: ApprovalListCommand,
        *,
        detail: bool,
    ) -> RuntimeSessions:
        self._bind(actor, "session.get" if detail else "session.list")
        if command.project_uuid != actor.project_uuid:
            raise AccessDenied("Runtime project binding mismatch")
        if detail and not isinstance(command, SessionGetCommand):
            raise InvalidInput("Session selector required")
        query = command
        return RuntimeSessions(
            await self._services.reader.list_sessions(self._request, query), detail
        )

    async def approvals(
        self, actor: RuntimeActor, command: ApprovalListCommand
    ) -> RuntimeApprovals:
        self._bind(actor, "approval.list")
        if command.project_uuid != actor.project_uuid:
            raise AccessDenied("Runtime project binding mismatch")
        query = command
        return RuntimeApprovals(await self._services.reader.list(self._request, query))

    async def events(self, actor: RuntimeActor, command: RuntimeEventQuery) -> RuntimeEvents:
        from authorization._runtime_events import read_events

        return await read_events(self._services.database, actor, command.window())

    async def execute(
        self,
        actor: RuntimeActor,
        action: RuntimeAction,
        command: RuntimeWriteCommand,
    ) -> RuntimeWriteReceipt:
        self._bind(actor, action)
        if command.project_uuid != actor.project_uuid:
            raise AccessDenied("Runtime project binding mismatch")
        commands = self._services.commands
        if action == "session.open" and isinstance(command, OpenSessionCommand):
            opened = command
            opened_outcome = await commands.open_normal(self._request, opened)
            return RuntimeWriteReceipt(opened_outcome.status, opened_outcome.body)
        if action == "session.revoke" and isinstance(command, RevokeSessionCommand):
            revoked = command
            revoked_outcome = await commands.revoke_session(self._request, revoked)
            return RuntimeWriteReceipt(revoked_outcome.status, revoked_outcome.body)
        if action == "session.request_elevation" and isinstance(command, RequestElevationCommand):
            requested = command
            scoped = await self._scoped_commands(requested)
            requested_outcome = await scoped.request_elevation(self._request, requested)
            return RuntimeWriteReceipt(requested_outcome.status, requested_outcome.body)
        if action == "session.resolve_elevation" and isinstance(command, ResolveElevationCommand):
            resolved = command
            scoped = await self._scoped_commands(resolved)
            resolved_outcome = await scoped.resolve_elevation(self._request, resolved)
            return RuntimeWriteReceipt(resolved_outcome.status, resolved_outcome.body)
        raise InvalidInput("Unknown Access command")

    async def _scopes(
        self,
        command: RequestElevationCommand | ResolveElevationCommand,
    ) -> tuple[SessionResourceGrant, ...]:
        if isinstance(command, RequestElevationCommand):
            return tuple(scope.domain() for scope in command.resources)
        if not command.approve:
            return ()
        async with self._services.database.transaction() as tx:
            approval = await tx.scalar(
                select(SessionApprovalRow).where(
                    SessionApprovalRow.id == command.approval_uuid,
                    SessionApprovalRow.project_id == command.project_uuid,
                )
            )
            if approval is None:
                raise AccessDenied("Current approval unavailable")
            scopes = approval.requested_grants.resources
        if scopes is None or len(scopes) > 32:
            raise AccessDenied("Current runtime resource owner unavailable")
        try:
            canonical_grants(scopes, set(HAND_EFFECT_AUDIENCES), None, unique=False)
        except ValueError:
            raise AccessDenied("Current runtime resource owner unavailable") from None
        return scopes

    async def _scoped_commands(
        self,
        command: RequestElevationCommand | ResolveElevationCommand,
    ) -> AccessRauthyCommandService:
        scopes = await self._scopes(command)
        if not scopes:
            return self._services.commands
        owners = await CurrentRuntimeResourceOwners.inspect_owners(
            command.project_uuid,
            scopes,
            node_resources=self._peers.node_resources,
        )
        return AccessRauthyCommandService(
            database=self._services.database,
            idempotency=IdempotentCommandExecutor(
                self._services.database, self._services.encryption_key
            ),
            attestor=self._services.attestor,
            resource_owner=owners,
        )
