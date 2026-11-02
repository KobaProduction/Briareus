"""Current human binding, isolated placement and short effect-lease invariants."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

RuntimePermission = Literal["use_resources", "approve_agent_session"]


class RuntimeAccessDenied(Exception):
    """Current independent authority does not permit this runtime operation."""


class RuntimeIdentityRequired(Exception):
    """The BFF identity is missing, obsolete or not canonical."""


@dataclass(frozen=True, slots=True)
class RuntimeIdentity:
    issuer: str
    subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime

    def require_current(self, now: datetime) -> None:
        if self.actor_uuid.version != 4 or self.project_uuid.version != 4:
            raise RuntimeIdentityRequired
        if self.expires_at.tzinfo is None or self.expires_at <= now:
            raise RuntimeIdentityRequired


@dataclass(frozen=True, slots=True)
class RuntimeActor:
    issuer: str
    subject: str
    actor_uuid: UUID
    project_uuid: UUID
    expires_at: datetime
    permissions: tuple[RuntimePermission, ...]
    role: Literal["user", "operator"]

    def require_resources(self) -> None:
        if "use_resources" not in self.permissions:
            raise RuntimeAccessDenied("Current project resource permission required")

    def require_active(self, now: datetime) -> None:
        if self.expires_at <= now:
            raise RuntimeAccessDenied("Current Platform actor expired")


def bind_runtime_actor(
    identity: RuntimeIdentity,
    actor: RuntimeActor,
    *,
    began: datetime,
    now: datetime,
) -> RuntimeActor:
    expected = (identity.issuer, identity.subject, identity.actor_uuid, identity.project_uuid)
    actual = (actor.issuer, actor.subject, actor.actor_uuid, actor.project_uuid)
    if actual != expected or actor.expires_at.tzinfo is None:
        raise RuntimeAccessDenied("Platform context binding mismatch")
    if not began < actor.expires_at <= now + timedelta(seconds=30):
        raise RuntimeAccessDenied("Platform context binding mismatch")
    return replace(actor, expires_at=min(actor.expires_at, identity.expires_at))


@dataclass(frozen=True, slots=True)
class RuntimePlacement:
    hand: str
    project_uuid: UUID
    isolated: bool
    resource_id: str
    resource_revision: int
    tools: tuple[str, ...]

    def require_project(self, project_uuid: UUID) -> None:
        expected = f"project-{self.hand}:{project_uuid}:{self.resource_revision:064x}"
        if self.project_uuid != project_uuid or not self.isolated or self.resource_revision < 1:
            raise RuntimeAccessDenied("Current Terminal placement not verified")
        if self.resource_id != expected or not 1 <= len(self.tools) <= 32:
            raise RuntimeAccessDenied("Current Terminal placement not verified")


def effect_expiry(
    *,
    now_seconds: int,
    lease_seconds: int,
    actor_expires_at: datetime,
    session_expires_at: datetime,
) -> int:
    expiry = min(
        now_seconds + lease_seconds,
        int(actor_expires_at.timestamp()),
        int(session_expires_at.timestamp()),
    )
    if expiry <= now_seconds:
        raise RuntimeAccessDenied("Current authority expired")
    return expiry
