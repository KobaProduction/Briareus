"""AgentSession receipt invariants, without transport or provider dependencies."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from owner_protocol.domain.authority import _uuid_v4 as _uuid_v4_source

uuid4 = _uuid_v4_source
del _uuid_v4_source

OPERATIONS = frozenset(
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


def valid_label(value: object) -> bool:
    if value is None:
        return True
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and all(ord(char) >= 32 and ord(char) != 127 for char in value)
    )


def aware_timestamp(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def optional_timestamp(value: object) -> bool:
    return value is None or aware_timestamp(value)


def positive_revision(value: object) -> bool:
    return type(value) is int and value >= 1


def boolean(value: object) -> bool:
    return type(value) is bool


def bounded_resources(value: object) -> bool:
    return isinstance(value, tuple) and len(value) <= 32


def valid_operations(value: object) -> bool:
    if not isinstance(value, tuple) or not 1 <= len(value) <= 32:
        return False
    if not all(isinstance(operation, str) and operation in OPERATIONS for operation in value):
        return False
    return len(set(value)) == len(value)


@dataclass(frozen=True, slots=True)
class ApprovalLifecycle:
    status: str
    requester: UUID
    parent_session: UUID
    resolver: UUID | None
    issued_session: UUID | None

    def valid(self) -> bool:
        if self.resolver is not None and not uuid4(self.resolver):
            return False
        if self.issued_session is not None and not uuid4(self.issued_session):
            return False
        if self.status == "pending":
            return self.resolver is None and self.issued_session is None
        if self.status not in {"approved", "rejected"}:
            return False
        return (
            self.resolver is not None
            and self.resolver != self.requester
            and ((self.status == "approved") == (self.issued_session is not None))
            and self.issued_session != self.parent_session
        )


EffectHand = Literal["files", "terminal", "web", "svc", "reverse", "infrastructure", "serena"]


@dataclass(frozen=True, slots=True)
class EffectScope:
    """An effect identity; no provider wire dictionaries enter domain comparisons."""

    hand: EffectHand
    tool: str
    action: str
    resource_kind: str
    resource_id: str


def valid_effects(
    effects: tuple[EffectScope, ...],
    *,
    operations: tuple[str, ...],
    unique: bool,
) -> bool:
    if len(effects) > 32 or not all(valid_effect(effect) for effect in effects):
        return False
    if any(effect.action not in operations for effect in effects):
        return False
    return not unique or len(set(effects)) == len(effects)


def bounded_scope_text(value: object, limit: int) -> bool:
    return isinstance(value, str) and 1 <= len(value) <= limit


def valid_effect(value: object) -> bool:
    if not isinstance(value, EffectScope):
        return False
    return (
        value.hand in {"files", "terminal", "web", "svc", "reverse", "infrastructure", "serena"}
        and bounded_scope_text(value.tool, 128)
        and bounded_scope_text(value.action, 128)
        and bounded_scope_text(value.resource_kind, 64)
        and bounded_scope_text(value.resource_id, 512)
    )


def resolution_actions(
    lifecycle: ApprovalLifecycle,
    *,
    actor: UUID,
    approver: bool,
    expires_at: datetime,
    now: datetime,
) -> tuple[str, ...]:
    if (
        lifecycle.status == "pending"
        and approver
        and lifecycle.requester != actor
        and expires_at > now
    ):
        return ("approve", "deny")
    return ()


@dataclass(frozen=True, slots=True)
class SessionState:
    status: str
    is_elevated: bool
    elevation_policy: str
    hard_expires_at: datetime
    allowed_actions: tuple[str, ...]

    def valid(self, *, now: datetime, approver: bool) -> bool:
        if self.status not in {"active", "revoked", "expired"}:
            return False
        if not boolean(self.is_elevated):
            return False
        if self.elevation_policy not in {"fixed", "requestable"}:
            return False
        if not aware_timestamp(self.hard_expires_at):
            return False
        expired = self.hard_expires_at <= now
        if self.status == "active" and expired:
            return False
        if self.status == "expired" and not expired:
            return False
        if self.allowed_actions not in ((), ("revoke",)):
            return False
        return not self.allowed_actions or (approver and self.status == "active" and not expired)
