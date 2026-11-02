"""Canonical Access command models shared by the existing transport adapters."""

from __future__ import annotations

from uuid import UUID

from pydantic import Field, field_validator, model_validator

from authorization.domain.resource_scopes import canonical_grants
from authorization.domain.sessions import SessionResourceGrant
from runtime_peer.access_management_wire import (
    AccessListInput,
    AccessOperation,
    EffectScopeWire,
    HandName,
    OpenSessionInput,
    RequestElevationInput,
    ResolveElevationInput,
    RevokeSessionInput,
    SessionGetInput,
)
from runtime_peer.access_management_wire import ResourceScopeWire as ScopeResource
from service_runtime._uuid_field_validation import _project_uuid_v4

__all__ = (
    "AccessCommand",
    "ApprovalListCommand",
    "OpenSessionCommand",
    "RequestElevationCommand",
    "ResolveElevationCommand",
    "RevokeSessionCommand",
    "ScopeEffect",
    "ScopeResource",
    "SessionGetCommand",
)

_OPERATIONS = frozenset(
    {
        "files.read",
        "files.write",
        "project.metadata.read",
        "terminal.execute",
        "web.access",
        "analysis.import",
        "agents.manage",
        "integrations.use",
        "variables.use",
        "integrations.manage",
        "variables.manage",
    }
)


class _ScopeGrantProjection[HandT: str, ResourceT: ScopeResource]:
    hand: HandT
    tool: str
    action: str
    resource: ResourceT

    def domain(self) -> SessionResourceGrant:
        return SessionResourceGrant(
            self.hand, self.tool, self.action, self.resource.kind, self.resource.id
        )


class ScopeEffect(EffectScopeWire, _ScopeGrantProjection[HandName, ScopeResource]):
    resource: ScopeResource


class AccessCommand(AccessOperation):
    project_uuid: UUID

    @field_validator("project_uuid")
    @classmethod
    def uuid_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("trusted scope and operation require UUIDv4")
        return value


class OpenSessionCommand(AccessCommand, OpenSessionInput):
    @model_validator(mode="after")
    def safe_label(self) -> OpenSessionCommand:
        if self.label is not None and (
            not 1 <= len(self.label.strip()) <= 128
            or self.label != self.label.strip()
            or any(ord(c) < 32 or ord(c) == 127 for c in self.label)
        ):
            raise ValueError("AgentSession label must be canonical and readable")
        return self


class RequestElevationCommand(AccessCommand, RequestElevationInput):
    resources: tuple[ScopeEffect, ...] = Field(default=(), max_length=32)

    @model_validator(mode="after")
    def exact_scope(self) -> RequestElevationCommand:
        if self.agent_session_uuid.version != 4:
            raise ValueError("AgentSession requires UUIDv4")
        if (
            len(set(self.operations)) != len(self.operations)
            or not set(self.operations) <= _OPERATIONS
        ):
            raise ValueError("unsafe operation list")
        normalized = self.resource_grants()
        # Do not create a misleading action-only elevated grant that no
        # V2 Hand can actually enforce against an exact owned resource.
        # Every elevated operation must be represented by >=1 exact scope.
        if {scope.action for scope in normalized} != set(self.operations):
            raise ValueError("every elevated Hand action needs a resource scope")
        return self

    def resource_grants(self) -> tuple[SessionResourceGrant, ...]:
        return canonical_grants(
            tuple(item.domain() for item in self.resources), set(self.operations), self.project_uuid
        )


class ResolveElevationCommand(AccessCommand, ResolveElevationInput):
    @model_validator(mode="after")
    def safe_subset(self) -> ResolveElevationCommand:
        if self.approval_uuid.version != 4:
            raise ValueError("approval requires UUIDv4")
        if self.allowed_operations is not None and (
            len(set(self.allowed_operations)) != len(self.allowed_operations)
            or not set(self.allowed_operations) <= _OPERATIONS
        ):
            raise ValueError("invalid approval operation subset")
        return self


class RevokeSessionCommand(AccessCommand, RevokeSessionInput):
    @field_validator("agent_session_uuid")
    @classmethod
    def session_v4(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("AgentSession requires UUIDv4")
        return value


class ApprovalListCommand(AccessListInput):
    project_uuid: UUID

    canonical_uuid = field_validator("project_uuid")(staticmethod(_project_uuid_v4))


class SessionGetCommand(ApprovalListCommand, SessionGetInput):
    limit: int = Field(default=1, strict=True, ge=1, le=1)

    @field_validator("session_uuid")
    @classmethod
    def canonical_session_uuid(cls, value: UUID) -> UUID:
        if value.version != 4:
            raise ValueError("AgentSession must be UUIDv4")
        return value
