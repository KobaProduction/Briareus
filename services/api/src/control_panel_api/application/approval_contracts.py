"""Typed Authorization owner boundary, independent of HTTP presentation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol, runtime_checkable
from uuid import UUID

from control_panel_api.domain.approval_policy import EffectScope
from control_panel_api.domain.platform_authority import ResolvedPlatformUser


@dataclass(frozen=True, slots=True)
class ApprovalSnapshot:
    approval_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    requested_by_user_uuid: UUID
    status: Literal["pending", "approved", "rejected"]
    version: int
    requested_operations: tuple[str, ...]
    requested_resources: tuple[EffectScope, ...]
    requested_expires_at: datetime
    resolved_by_user_uuid: UUID | None = None
    issued_session_uuid: UUID | None = None
    label: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class OpenSessionSnapshot:
    session_uuid: UUID
    project_uuid: UUID
    revision: int
    status: Literal["active"]
    is_elevated: Literal[False]
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[EffectScope, ...]


@dataclass(frozen=True, slots=True)
class CurrentSessionSnapshot:
    session_uuid: UUID
    project_uuid: UUID
    created_by_user_uuid: UUID
    revision: int
    status: Literal["active", "revoked", "expired"]
    is_elevated: bool
    elevation_policy: Literal["fixed", "requestable"]
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[EffectScope, ...]
    allowed_actions: tuple[Literal["revoke"], ...]
    label: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class GrantSnapshot:
    session_uuid: UUID
    project_uuid: UUID
    status: Literal["active", "revoked"]
    revision: int


class OwnerManagementUnavailable(Exception):
    """Trusted Authorization owner or fresh permission proof unavailable."""


class OwnerManagementDenied(Exception):
    """Actual owner denied this actor/Project/request scope."""


class OwnerManagementConflict(Exception):
    """Owner detected stale revision or idempotency conflict."""


class OwnerManagementNotFound(Exception):
    """A scoped session is absent or not visible to this current actor."""


class OwnerManagementInvalidInput(Exception):
    """Actual Access owner rejected an invalid scoped command."""


class ApprovalManagementPort(Protocol):
    """Server-side authenticated transport to Authorization's owner API."""

    async def open_normal(
        self,
        *,
        actor: UUID,
        project: UUID,
        elevation_policy: Literal["fixed", "requestable"],
        label: str | None,
        operation: UUID,
    ) -> OpenSessionSnapshot: ...

    async def list_sessions(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[CurrentSessionSnapshot, ...]: ...

    async def get_session(
        self, *, actor: UUID, project: UUID, session: UUID
    ) -> CurrentSessionSnapshot: ...

    async def list_approvals(
        self, *, actor: UUID, project: UUID, limit: int
    ) -> tuple[ApprovalSnapshot, ...]: ...

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
    ) -> ApprovalSnapshot: ...

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
    ) -> ApprovalSnapshot: ...

    async def revoke_session(
        self, *, actor: UUID, project: UUID, session: UUID, expected_revision: int, operation: UUID
    ) -> GrantSnapshot: ...


@runtime_checkable
class ActorBoundApprovalSource(Protocol):
    def for_actor(self, proof: ResolvedPlatformUser) -> ApprovalManagementPort: ...


ApprovalSource = ApprovalManagementPort | ActorBoundApprovalSource
