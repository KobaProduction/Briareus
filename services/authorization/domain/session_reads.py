"""Current read visibility and truthful session/approval actions."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from authorization.domain.files_read import uuid_v4 as uuid_v4
from authorization.domain.sessions import SessionResourceGrant


class SessionReadDenied(Exception):
    """The current actor attestation does not authorize this Project read."""


class SessionReadUnavailable(Exception):
    """The current owner snapshot cannot be safely presented."""


def optional_uuid_v4(value: object) -> bool:
    return value is None or uuid_v4(value)


def aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def strict_boolean(value: object) -> bool:
    return type(value) is bool


@dataclass(frozen=True, slots=True)
class VerifiedApprovalActor:
    actor_uuid: UUID
    project_uuid: UUID
    can_approve: bool
    issuer: str
    target_audience: str
    expires_at: datetime

    def require_current(self, project_uuid: UUID, now: datetime) -> None:
        identity_matches = uuid_v4(self.actor_uuid) and self.project_uuid == project_uuid
        authority_matches = (
            strict_boolean(self.can_approve)
            and self.issuer == "rauthy"
            and self.target_audience == "briareus:access"
        )
        time_matches = aware_datetime(self.expires_at) and now < self.expires_at <= now + timedelta(
            seconds=30
        )
        if not (identity_matches and authority_matches and time_matches):
            raise SessionReadDenied

    def require_visible(self, project_uuid: UUID, owner_uuid: UUID) -> None:
        if project_uuid != self.project_uuid or (
            not self.can_approve and owner_uuid != self.actor_uuid
        ):
            raise SessionReadUnavailable


@dataclass(frozen=True, slots=True)
class ApprovalReadEntry:
    request_uuid: UUID
    project_uuid: UUID
    session_uuid: UUID
    requested_by_user_uuid: UUID
    label: str | None
    created_at: datetime
    status: str
    version: int
    operations: tuple[str, ...]
    resources: tuple[SessionResourceGrant, ...]
    requested_expires_at: datetime
    resolved_by_user_uuid: UUID | None
    issued_session_uuid: UUID | None
    allowed_actions: tuple[str, ...] = ()

    def require_valid(self, actor: VerifiedApprovalActor) -> None:
        actor.require_visible(self.project_uuid, self.requested_by_user_uuid)
        identities_valid = all(
            uuid_v4(value)
            for value in (
                self.request_uuid,
                self.session_uuid,
                self.requested_by_user_uuid,
            )
        )
        resolution_valid = optional_uuid_v4(self.resolved_by_user_uuid) and optional_uuid_v4(
            self.issued_session_uuid
        )
        state_valid = (
            type(self.version) is int
            and self.version >= 1
            and self.status in {"pending", "approved", "rejected"}
            and aware_datetime(self.requested_expires_at)
        )
        if not (identities_valid and resolution_valid and state_valid):
            raise SessionReadUnavailable

    def actions(self, actor: VerifiedApprovalActor, now: datetime) -> tuple[str, ...]:
        if (
            actor.can_approve
            and self.requested_by_user_uuid != actor.actor_uuid
            and self.status == "pending"
            and self.requested_expires_at > now
        ):
            return ("approve", "deny")
        return ()


@dataclass(frozen=True, slots=True)
class SessionReadEntry:
    session_uuid: UUID
    project_uuid: UUID
    created_by_user_uuid: UUID
    label: str | None
    created_at: datetime
    revision: int
    status: str
    is_elevated: bool
    elevation_policy: str
    hard_expires_at: datetime
    operations: tuple[str, ...]
    resources: tuple[SessionResourceGrant, ...]
    revoked_at: datetime | None
    allowed_actions: tuple[str, ...] = ()

    def require_valid(self, actor: VerifiedApprovalActor) -> None:
        actor.require_visible(self.project_uuid, self.created_by_user_uuid)
        identities_valid = uuid_v4(self.session_uuid) and uuid_v4(self.created_by_user_uuid)
        state_valid = (
            type(self.revision) is int
            and self.revision >= 1
            and self.status in {"active", "revoked"}
            and strict_boolean(self.is_elevated)
            and self.elevation_policy in {"fixed", "requestable"}
            and aware_datetime(self.hard_expires_at)
        )
        revocation_valid = (self.status == "revoked") == (self.revoked_at is not None)
        if not (identities_valid and state_valid and revocation_valid):
            raise SessionReadUnavailable

    def current_status(self, now: datetime) -> str:
        return "expired" if self.status == "active" and self.hard_expires_at <= now else self.status
