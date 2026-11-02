"""AgentSession lifecycle and approval invariants, independent of persistence."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from uuid import UUID

NORMAL_TTL = timedelta(hours=24)
ELEVATED_HARD_TTL = timedelta(minutes=5)
SAFE_BASIC_GRANTS = frozenset({"files.read", "project.metadata.read"})
SUPPORTED_GRANTS = frozenset(
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


class SessionAccessDenied(Exception):
    """A lifecycle operation would violate the current authority or scope."""


class SessionConflict(Exception):
    """A lifecycle operation refers to an obsolete state or revision."""


class InvalidSessionInput(Exception):
    """A requested session value is outside the supported contract."""


def checked_grants(grants: tuple[str, ...], *, allow_privileged: bool) -> tuple[str, ...]:
    value = tuple(sorted(set(grants)))
    if len(value) > 32 or not set(value).issubset(SUPPORTED_GRANTS):
        raise InvalidSessionInput("unknown or excessive AgentSession grants")
    if not allow_privileged and not set(value).issubset(SAFE_BASIC_GRANTS):
        raise SessionAccessDenied("basic session cannot grant privileged operations")
    return value


def checked_label(label: str | None) -> str | None:
    if label is None:
        return None
    value = label.strip()
    if not 1 <= len(value) <= 128 or any(ord(char) < 32 for char in value):
        raise InvalidSessionInput("AgentSession label must be 1-128 readable characters")
    return value


@dataclass(frozen=True, slots=True)
class SessionResourceGrant:
    hand: str
    tool: str
    action: str
    resource_kind: str
    resource_id: str


@dataclass(frozen=True, slots=True)
class SessionState:
    session_uuid: UUID
    project_uuid: UUID
    created_by_principal_uuid: UUID
    grants: tuple[str, ...]
    is_elevated: bool
    hard_expires_at: datetime
    status: str
    version: int
    label: str | None
    elevation_policy: str
    created_at: datetime
    revoked_at: datetime | None = None
    resources: tuple[SessionResourceGrant, ...] = ()

    def require_project(self, project_uuid: UUID) -> None:
        if self.project_uuid != project_uuid:
            raise SessionAccessDenied("Project access denied")

    def require_active(self, now: datetime) -> None:
        if self.status != "active" or self.hard_expires_at <= now:
            raise SessionAccessDenied("SESSION_EXPIRED")

    def require_operation(self, operation: str, now: datetime) -> None:
        self.require_active(now)
        if operation not in self.grants:
            raise SessionAccessDenied("AGENT_SESSION_GRANT_REQUIRED")

    def require_elevation_request(self, expected_revision: int, now: datetime) -> None:
        if not 1 <= expected_revision <= 2**63 - 1:
            raise InvalidSessionInput("expected AgentSession revision invalid")
        if self.version != expected_revision:
            raise SessionConflict("AgentSession grant revision changed")
        self.require_active(now)
        if self.elevation_policy != "requestable" or self.is_elevated:
            raise SessionAccessDenied("fixed or elevated session cannot request more grants")

    def revoked(self, now: datetime) -> SessionState:
        if self.status != "active":
            return self
        return replace(self, status="revoked", revoked_at=now, version=self.version + 1)


def normal_session(
    *,
    session_uuid: UUID,
    project_uuid: UUID,
    actor_uuid: UUID,
    elevation_policy: str,
    label: str | None,
    now: datetime,
) -> SessionState:
    if elevation_policy not in {"fixed", "requestable"}:
        raise InvalidSessionInput("elevation_policy must be fixed or requestable")
    return SessionState(
        session_uuid=session_uuid,
        project_uuid=project_uuid,
        created_by_principal_uuid=actor_uuid,
        grants=tuple(sorted(SAFE_BASIC_GRANTS)),
        is_elevated=False,
        hard_expires_at=now + NORMAL_TTL,
        status="active",
        version=1,
        label=checked_label(label),
        elevation_policy=elevation_policy,
        created_at=now,
    )


@dataclass(frozen=True, slots=True)
class ElevationRequest:
    request_uuid: UUID
    session_uuid: UUID
    project_uuid: UUID
    requested_by_user_uuid: UUID
    grants: tuple[str, ...]
    resources: tuple[SessionResourceGrant, ...]
    requested_expires_at: datetime
    status: str = "pending"
    version: int = 1
    resolved_by_user_uuid: UUID | None = None
    issued_session_uuid: UUID | None = None
    resolved_at: datetime | None = None

    def require_resolution(
        self,
        *,
        project_uuid: UUID,
        actor_uuid: UUID,
        approve: bool,
        expected_version: int,
    ) -> None:
        if self.project_uuid != project_uuid:
            raise SessionAccessDenied("Project access denied")
        if self.status != "pending":
            raise SessionConflict("elevation request already resolved")
        if self.version != expected_version:
            raise SessionConflict("AgentSession approval revision mismatch")
        if approve and self.requested_by_user_uuid == actor_uuid:
            raise SessionAccessDenied("an elevation requester cannot approve their own request")

    def approved_grants(self, allowed: tuple[str, ...] | None) -> tuple[str, ...]:
        requested = checked_grants(self.grants, allow_privileged=True)
        actual = checked_grants(
            allowed if allowed is not None else requested, allow_privileged=True
        )
        if not set(actual).issubset(requested):
            raise SessionAccessDenied("approved grants exceed original request")
        return actual

    def elevated_session(
        self,
        *,
        base: SessionState,
        session_uuid: UUID,
        grants: tuple[str, ...],
        resources: tuple[SessionResourceGrant, ...],
        now: datetime,
    ) -> SessionState:
        expires_at = min(self.requested_expires_at, now + ELEVATED_HARD_TTL)
        if expires_at <= now:
            raise SessionConflict("elevation request TTL expired")
        return SessionState(
            session_uuid=session_uuid,
            project_uuid=self.project_uuid,
            created_by_principal_uuid=self.requested_by_user_uuid,
            grants=grants,
            resources=resources,
            is_elevated=True,
            hard_expires_at=expires_at,
            status="active",
            version=1,
            label=base.label,
            elevation_policy="fixed",
            created_at=now,
        )

    def resolved(
        self, *, actor_uuid: UUID, issued_session_uuid: UUID | None, now: datetime
    ) -> ElevationRequest:
        return replace(
            self,
            status="approved" if issued_session_uuid is not None else "rejected",
            version=self.version + 1,
            resolved_by_user_uuid=actor_uuid,
            issued_session_uuid=issued_session_uuid,
            resolved_at=now,
        )


def require_base_for_resolution(base: SessionState, project_uuid: UUID, now: datetime) -> None:
    if base.project_uuid != project_uuid:
        raise SessionAccessDenied("elevation request references another Project")
    if base.status != "active" or base.hard_expires_at <= now:
        raise SessionConflict("base AgentSession expired or revoked")


def checked_elevation_seconds(seconds: int) -> timedelta:
    if not 1 <= seconds <= 300:
        raise InvalidSessionInput("elevated hard TTL must be at most 300 seconds")
    return timedelta(seconds=seconds)


def source_approved_operations(
    requested: tuple[str, ...],
    allowed: tuple[str, ...] | None,
) -> tuple[str, ...]:
    if not set(requested).issubset(SUPPORTED_GRANTS):
        raise SessionAccessDenied("invalid stored approval grants")
    final = tuple(sorted(set(allowed if allowed is not None else requested)))
    if not final or not set(final).issubset(SUPPORTED_GRANTS):
        raise SessionAccessDenied("unapproved elevated grant")
    if not set(final).issubset(requested):
        raise SessionAccessDenied("approved grants exceed original request")
    return final
