"""Request-bound Files read authority and its non-extensible lifetime."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from owner_protocol.domain.authority import _uuid_v4 as _uuid_v4_source

uuid_v4 = _uuid_v4_source
del _uuid_v4_source


class ReadAuthenticationRequired(Exception):
    """The authenticated caller does not match this effect."""


class ReadScopeDenied(Exception):
    """Current authority no longer permits this exact read."""


class ReadAuthorityUnavailable(Exception):
    """An independent authority cannot supply current evidence."""


@dataclass(frozen=True, slots=True)
class ReadScope:
    project_uuid: UUID
    agent_session_uuid: UUID
    effect_key: str | None
    expected_grant_revision: int
    expected_resource_revision: int


@dataclass(frozen=True, slots=True)
class ReadCaller:
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    consumer: str
    authority: str
    peer_audience: str
    effect_key: str | None
    expires_at: datetime

    def require_scope(self, scope: ReadScope, now: datetime) -> None:
        identity_matches = (
            uuid_v4(self.actor_uuid)
            and self.project_uuid == scope.project_uuid
            and self.agent_session_uuid == scope.agent_session_uuid
        )
        authority_matches = (
            self.consumer == "hand"
            and self.authority == "rauthy"
            and self.peer_audience == "briareus:access"
            and self.effect_key == scope.effect_key
        )
        if not (identity_matches and authority_matches and live_at(self.expires_at, now)):
            raise ReadAuthenticationRequired("verified Files caller required")


@dataclass(frozen=True, slots=True)
class ReadGrant:
    actor_uuid: UUID
    project_uuid: UUID
    agent_session_uuid: UUID
    revision: int
    expires_at: datetime

    def require_scope(self, scope: ReadScope, caller: ReadCaller, now: datetime) -> None:
        identity_matches = (
            self.actor_uuid == caller.actor_uuid
            and self.project_uuid == scope.project_uuid
            and self.agent_session_uuid == scope.agent_session_uuid
        )
        revision_matches = (
            type(self.revision) is int and self.revision == scope.expected_grant_revision
        )
        if not (identity_matches and revision_matches and live_at(self.expires_at, now)):
            raise ReadScopeDenied("Files read current Access grant denied")
        if self.expires_at > caller.expires_at:
            raise ReadScopeDenied("Files read current Access grant denied")


@dataclass(frozen=True, slots=True)
class ReadResource:
    revision: int
    expires_at: datetime

    def require_revision(self, scope: ReadScope) -> None:
        if self.revision != scope.expected_resource_revision:
            raise ReadScopeDenied("Files resource scope or revision changed")


@dataclass(frozen=True, slots=True)
class ReadAuthorization:
    actor_uuid: UUID
    grant_revision: int
    resource_revision: int
    checked_at: datetime
    expires_at: datetime


def live_at(expires_at: object, now: datetime) -> bool:
    return isinstance(expires_at, datetime) and expires_at.tzinfo is not None and expires_at > now


def authorize_read(
    caller: ReadCaller,
    grant: ReadGrant,
    initial: ReadResource,
    current: ReadResource,
    now: datetime,
) -> ReadAuthorization:
    """Revalidation never extends the original proof's lifetime."""
    expires_at = min(
        caller.expires_at,
        grant.expires_at,
        initial.expires_at,
        current.expires_at,
        now + timedelta(seconds=5),
    )
    if expires_at <= now:
        raise ReadScopeDenied("Files read original authority expired")
    return ReadAuthorization(caller.actor_uuid, grant.revision, current.revision, now, expires_at)
