"""Cookie-bound human management delegated to the independent Access owner."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

from runtime_peer import PeerClient

from ._access_management_client import _ApprovalOwnerItem, _SessionOwnerItem
from ._oidc_approvals import (
    ApprovalSnapshot, CurrentSessionSnapshot, GrantSnapshot, OpenSessionSnapshot,
    OwnerManagementConflict, OwnerManagementDenied, OwnerManagementInvalidInput,
    OwnerManagementNotFound, OwnerManagementUnavailable,
)
from ._oidc_membership import ResolvedPlatformUser
from ._panel_events import panel_events


def _approval(raw: dict[str, object]) -> ApprovalSnapshot:
    item = _ApprovalOwnerItem.model_validate(raw)
    return ApprovalSnapshot(item.id, item.project_uuid, item.agent_session_uuid,
                            item.requested_by_user_uuid, item.status, item.version,
                            item.requested_operations, item.requested_resources,
                            item.requested_expires_at, item.resolved_by_user_uuid,
                            item.issued_session_uuid, item.label, item.created_at)


def _session(raw: dict[str, object]) -> CurrentSessionSnapshot:
    item = _SessionOwnerItem.model_validate(raw)
    return CurrentSessionSnapshot(item.session_uuid, item.project_uuid,
                                   item.created_by_user_uuid, item.revision, item.status,
                                   item.is_elevated, item.elevation_policy, item.hard_expires_at,
                                   item.operations, item.resources, item.allowed_actions, item.label, item.created_at)


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

    async def _call(self, action: str, actor: UUID, project: UUID,
                    command: dict[str, object]) -> dict[str, object]:
        proof = self.proof
        if (actor != proof.user_uuid or proof.expires_at <= datetime.now(UTC)
            or not any(item.project_uuid == project for item in proof.projects)):
            raise OwnerManagementDenied("Current project-bound actor required")
        try:
            status, body = await self.peer.call("/internal/v1/runtime/access", {
                "issuer": proof.issuer, "subject": proof.subject, "actor_uuid": str(actor),
                "project_uuid": str(project), "identity_expires_at": proof.expires_at.isoformat(),
                "action": action, "command": command,
            })
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
        expected = {"session.open": 201, "session.request_elevation": 202}.get(action, 200)
        if status != expected or proof.expires_at <= datetime.now(UTC):
            raise OwnerManagementUnavailable("Access did not confirm the operation")
        if action in {"session.open", "session.revoke", "session.request_elevation", "session.resolve_elevation"}:
            await panel_events.emit("management.events", action, {
                "project_id": str(project), "actor_id": str(actor),
                "operation_id": str(command.get("operation_uuid", ""))},
                visibility={"kind": "project", "id": str(project)})
            await panel_events.emit("system.notifications", action, {
                "project_id": str(project), "action": action},
                visibility={"kind": "project", "id": str(project)})
        return body

    async def open_normal(self, *, actor: UUID, project: UUID,
                          elevation_policy: Literal["fixed", "requestable"],
                          label: str | None, operation: UUID) -> OpenSessionSnapshot:
        raw = await self._call("session.open", actor, project, {
            "operation_uuid": str(operation), "elevation_policy": elevation_policy, "label": label,
        })
        return OpenSessionSnapshot(UUID(raw["session_uuid"]), UUID(raw["project_uuid"]),
                                    raw["revision"], raw["status"], raw["is_elevated"],
                                    raw["elevation_policy"], datetime.fromisoformat(raw["hard_expires_at"]),
                                    tuple(raw["operations"]), tuple(raw["resources"]))

    async def list_sessions(self, *, actor: UUID, project: UUID,
                            limit: int) -> tuple[CurrentSessionSnapshot, ...]:
        raw = await self._call("session.list", actor, project, {"limit": limit})
        return tuple(_session(item) for item in raw["items"])

    async def get_session(self, *, actor: UUID, project: UUID, session: UUID) -> CurrentSessionSnapshot:
        raw = await self._call("session.get", actor, project, {"limit": 1, "session_uuid": str(session)})
        return _session(raw["item"])

    async def list_approvals(self, *, actor: UUID, project: UUID,
                             limit: int) -> tuple[ApprovalSnapshot, ...]:
        raw = await self._call("approval.list", actor, project, {"limit": limit})
        return tuple(_approval(item) for item in raw["items"])

    async def request_elevation(self, *, actor: UUID, project: UUID, session: UUID,
                                operations: tuple[str, ...], resources: tuple[dict[str, object], ...],
                                seconds: int, expected_grant_revision: int,
                                operation: UUID) -> ApprovalSnapshot:
        raw = await self._call("session.request_elevation", actor, project, {
            "operation_uuid": str(operation), "agent_session_uuid": str(session),
            "expected_grant_revision": expected_grant_revision, "operations": list(operations),
            "resources": list(resources), "seconds": seconds,
        })
        return _approval(raw)

    async def resolve_elevation(self, *, actor: UUID, project: UUID, approval: UUID,
                                expected_version: int, approve: bool,
                                allowed_operations: tuple[str, ...] | None,
                                operation: UUID) -> ApprovalSnapshot:
        raw = await self._call("session.resolve_elevation", actor, project, {
            "operation_uuid": str(operation), "approval_uuid": str(approval),
            "expected_approval_version": expected_version, "approve": approve,
            "allowed_operations": list(allowed_operations) if allowed_operations is not None else None,
        })
        return _approval(raw)

    async def revoke_session(self, *, actor: UUID, project: UUID, session: UUID,
                              expected_revision: int, operation: UUID) -> GrantSnapshot:
        raw = await self._call("session.revoke", actor, project, {
            "operation_uuid": str(operation), "agent_session_uuid": str(session),
            "expected_grant_revision": expected_revision,
        })
        return GrantSnapshot(UUID(raw["session_uuid"]), UUID(raw["project_uuid"]),
                              raw["status"], raw["revision"])
