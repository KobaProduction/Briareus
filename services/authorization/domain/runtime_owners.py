"""Exact protected-resource selection against current owner evidence."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from authorization.domain.sessions import SessionResourceGrant as RuntimeOwnerScope

__all__ = (
    "RuntimeOwnerBinding",
    "RuntimeOwnerEvidence",
    "RuntimeOwnerScope",
    "RuntimeOwnerTool",
    "bind_owner_scope",
    "require_node_binding",
)


@dataclass(frozen=True, slots=True)
class RuntimeOwnerBinding:
    project_uuid: UUID
    resource_id: str
    revision: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class RuntimeOwnerTool:
    action: str
    resource_kind: str


@dataclass(frozen=True, slots=True)
class RuntimeOwnerEvidence:
    scope: RuntimeOwnerScope
    binding: RuntimeOwnerBinding


def bind_owner_scope(
    scope: RuntimeOwnerScope,
    binding: RuntimeOwnerBinding,
    tool: RuntimeOwnerTool,
) -> RuntimeOwnerEvidence:
    expected = (tool.action, tool.resource_kind, binding.resource_id)
    actual = (scope.action, scope.resource_kind, scope.resource_id)
    if actual != expected:
        raise ValueError("Scope belongs to another Node module storage")
    return RuntimeOwnerEvidence(scope, binding)


def require_node_binding(
    *,
    project_uuid: UUID,
    binding_project: UUID,
    resource_id: str,
    expected_resource: str,
    expires_at: int,
    now: float,
) -> None:
    if binding_project != project_uuid or not now < expires_at <= now + 5:
        raise ValueError("Current node Files binding mismatch")
    if resource_id != expected_resource:
        raise ValueError("Current node Files binding mismatch")
