"""Cookie-bound human management delegated to the independent Access owner."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from control_panel_api.application.approval_scopes import ScopedEffectPayload
from control_panel_api.application.owner_event_relay import OwnerEventPage
from control_panel_api.application.runtime_effect_contracts import (
    RuntimeHand,
    RuntimePermit,
    TerminalCommand,
)
from control_panel_api.domain.approval_policy import EffectScope
from control_panel_api.domain.event_scope import EventScope
from control_panel_api.domain.owner_events import EventFeed
from control_panel_api.domain.platform_authority import ResolvedPlatformUser
from control_panel_api.domain.realtime_payloads import AccessMutation, AccessNotification
from control_panel_api.infrastructure.owner_event_decoder import decode_page
from control_panel_api.infrastructure.runtime_access_codec import approval as decode_approval
from control_panel_api.infrastructure.runtime_access_codec import (
    approval_list,
    opened_session,
    revoked_session,
    session_detail,
    session_list,
)
from runtime_peer import PeerClient
from runtime_peer.access_management_wire import (
    AccessListInput,
    OpenSessionInput,
    RequestElevationInput,
    ResolveElevationInput,
    RevokeSessionInput,
    RuntimeHumanIdentity,
    RuntimeResourceInput,
    SessionGetInput,
)
from runtime_peer.event_window_wire import EventWindowRequest
from runtime_peer.response_decoding import successful_reply
from runtime_peer.runtime_resource_receipts import RuntimeResources

from ._panel_events import panel_events
from .application.approval_contracts import (
    ApprovalSnapshot,
    CurrentSessionSnapshot,
    GrantSnapshot,
    OpenSessionSnapshot,
    OwnerManagementConflict,
    OwnerManagementDenied,
    OwnerManagementInvalidInput,
    OwnerManagementNotFound,
    OwnerManagementUnavailable,
)

type HumanRuntimeInput = (
    OpenSessionInput
    | RequestElevationInput
    | ResolveElevationInput
    | RevokeSessionInput
    | SessionGetInput
    | AccessListInput
    | RuntimeResourceInput
    | EventWindowRequest
    | TerminalCommand
)


class RuntimeAccessClient:
    def __init__(self, peer: PeerClient) -> None:
        self.peer = peer

    def for_actor(self, proof: ResolvedPlatformUser) -> BoundRuntimeAccessClient:
        return BoundRuntimeAccessClient(self.peer, proof)

    async def close(self) -> None:
        await self.peer.close()


class BoundRuntimeAccessClient:
    """Immutable per-request identity binding; no global current-user state."""

    def __init__(self, peer: PeerClient, proof: ResolvedPlatformUser) -> None:
        self.peer, self.proof = peer, proof

    async def _call[T](
        self,
        action: str,
        actor: UUID,
        project: UUID,
        command: HumanRuntimeInput,
        decode: Callable[[object], T],
        *,
        operation: UUID | None = None,
    ) -> T:
        proof = self.proof
        if (
            actor != proof.user_uuid
            or proof.expires_at <= datetime.now(UTC)
            or not any(item.project_uuid == project for item in proof.projects)
        ):
            raise OwnerManagementDenied("Current project-bound actor required")
        expected = {"session.open": 201, "session.request_elevation": 202}.get(action, 200)
        try:
            identity = RuntimeHumanIdentity(
                issuer=proof.issuer,
                subject=proof.subject,
                actor_uuid=actor,
                project_uuid=project,
                identity_expires_at=proof.expires_at,
            )
            wire = identity.model_dump(mode="json")
            wire.update(
                action=action,
                command=command.model_dump(mode="json", exclude={"project_uuid"}),
            )
            _owner_reply = await self.peer.call(
                "/internal/v1/runtime/access",
                wire,
                decode=successful_reply(decode, statuses=(expected,)),
            )
            status, body = _owner_reply.status, _owner_reply.body
        except Exception:
            raise OwnerManagementUnavailable("Private Access peer unavailable") from None
        if status == 403:
            raise OwnerManagementDenied
        if status == 404:
            raise OwnerManagementNotFound
        if status == 409:
            raise OwnerManagementConflict
        if status == 422:
            raise OwnerManagementInvalidInput
        if status != expected or body is None or proof.expires_at <= datetime.now(UTC):
            raise OwnerManagementUnavailable("Access did not confirm the operation")
        if action in {
            "session.open",
            "session.revoke",
            "session.request_elevation",
            "session.resolve_elevation",
        }:
            if operation is None:
                raise ValueError("Committed Access mutation requires its operation UUID")
            await panel_events.emit(
                "management.events",
                action,
                AccessMutation(project, actor, operation),
                visibility=EventScope("project", id=project),
            )
            await panel_events.emit(
                "system.notifications",
                action,
                AccessNotification(project, action),
                visibility=EventScope("project", id=project),
            )
        return body

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot:
        return await self._call(
            "session.open",
            actor,
            project,
            OpenSessionInput(
                operation_uuid=operation, elevation_policy=elevation_policy, label=label
            ),
            decode=opened_session,
            operation=operation,
        )

    async def list_sessions(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[CurrentSessionSnapshot, ...]:
        return await self._call(
            "session.list", actor, project, AccessListInput(limit=limit), decode=session_list
        )

    async def get_session(
        self, *, actor: UUID, project: UUID, session: UUID
    ) -> CurrentSessionSnapshot:
        return await self._call(
            "session.get",
            actor,
            project,
            SessionGetInput(limit=1, session_uuid=session),
            decode=session_detail,
        )

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]:
        return await self._call(
            "approval.list", actor, project, AccessListInput(limit=limit), decode=approval_list
        )

    async def request_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        session: UUID,
        operations: tuple[str, ...],
        resources: tuple[EffectScope, ...],
        seconds: int,
        expected_grant_revision: int,
        operation: UUID,
    ) -> ApprovalSnapshot:
        return await self._call(
            "session.request_elevation",
            actor,
            project,
            RequestElevationInput(
                operation_uuid=operation,
                agent_session_uuid=session,
                expected_grant_revision=expected_grant_revision,
                operations=operations,
                resources=tuple(ScopedEffectPayload.from_scope(effect) for effect in resources),
                seconds=seconds,
            ),
            decode=decode_approval,
            operation=operation,
        )

    async def resolve_elevation(
        self,
        *,
        actor: UUID,
        project: UUID,
        approval: UUID,
        expected_version: int,
        approve: bool,
        allowed_operations: tuple[str, ...] | None,
        operation: UUID,
    ) -> ApprovalSnapshot:
        return await self._call(
            "session.resolve_elevation",
            actor,
            project,
            ResolveElevationInput(
                operation_uuid=operation,
                approval_uuid=approval,
                expected_approval_version=expected_version,
                approve=approve,
                allowed_operations=allowed_operations,
            ),
            decode=decode_approval,
            operation=operation,
        )

    async def revoke_session(
        self, *, actor: UUID, project: UUID, session: UUID, expected_revision: int, operation: UUID
    ) -> GrantSnapshot:
        return await self._call(
            "session.revoke",
            actor,
            project,
            RevokeSessionInput(
                operation_uuid=operation,
                agent_session_uuid=session,
                expected_grant_revision=expected_revision,
            ),
            decode=revoked_session,
            operation=operation,
        )

    async def resources(self, *, actor: UUID, project: UUID, hand: str) -> RuntimeResources:
        return await self._call(
            "resource.list",
            actor,
            project,
            RuntimeResourceInput(hand=hand),
            RuntimeResources.model_validate,
        )

    async def prepare(
        self, *, actor: UUID, hand: RuntimeHand, command: TerminalCommand
    ) -> RuntimePermit:
        return await self._call(
            hand + ".prepare", actor, command.project_uuid, command, RuntimePermit.model_validate
        )

    async def events(
        self, *, actor: UUID, project: UUID, window: EventWindowRequest
    ) -> OwnerEventPage:
        return await self._call(
            "events.read",
            actor,
            project,
            window,
            lambda body: decode_page(body, EventFeed("access", project)),
        )
