"""Rauthy-attested management authority and transitive session mutation rules."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from authorization.domain.session_reads import aware_datetime, strict_boolean, uuid_v4
from authorization.domain.sessions import (
    SUPPORTED_GRANTS,
    ElevationRequest,
    SessionAccessDenied,
    SessionConflict,
    SessionState,
)


@dataclass(frozen=True, slots=True)
class VerifiedAccessCommandActor:
    actor_uuid: UUID
    project_uuid: UUID
    operation_uuid: UUID
    action: Literal[
        "session.open", "session.request_elevation", "session.resolve_elevation", "session.revoke"
    ]
    can_use_resources: bool
    can_approve: bool
    identity_authority: str
    service_audience: str
    expires_at: datetime

    def require_active(
        self,
        *,
        project_uuid: UUID,
        operation_uuid: UUID,
        action: str,
        elevated: bool,
        now: datetime,
    ) -> None:
        scope_matches = (
            uuid_v4(self.actor_uuid)
            and self.project_uuid == project_uuid
            and self.operation_uuid == operation_uuid
            and self.action == action
        )
        authority_matches = (
            self.identity_authority == "rauthy"
            and self.service_audience == "briareus:access"
            and strict_boolean(self.can_use_resources)
            and strict_boolean(self.can_approve)
            and (self.can_approve if elevated else self.can_use_resources)
        )
        time_matches = aware_datetime(self.expires_at) and now < self.expires_at <= now + timedelta(
            seconds=30
        )
        if not (scope_matches and authority_matches and time_matches):
            raise SessionAccessDenied("current signed Rauthy/Platform operator scope required")


def require_requestable_session(
    state: SessionState, actor_uuid: UUID, expected_revision: int, now: datetime
) -> None:
    if state.created_by_principal_uuid != actor_uuid:
        raise SessionAccessDenied("an actor can request elevation only for own AgentSession")
    if state.version != expected_revision:
        raise SessionConflict("stale AgentSession revision")
    if (
        state.status != "active"
        or state.hard_expires_at <= now
        or state.elevation_policy != "requestable"
        or state.is_elevated
    ):
        raise SessionAccessDenied("AgentSession is not requestable and active")


def require_live_resolution(
    approval: ElevationRequest,
    base: SessionState | None,
    *,
    actor_uuid: UUID,
    project_uuid: UUID,
    expected_version: int,
    approve: bool,
    now: datetime,
) -> None:
    if approval.version != expected_version or approval.status != "pending":
        raise SessionConflict("approval revision or state changed")
    if approval.requested_by_user_uuid == actor_uuid:
        raise SessionAccessDenied("an elevation requester cannot resolve own request")
    if base is None:
        raise SessionAccessDenied("base AgentSession no longer eligible")
    require_eligible_base(base, approval, project_uuid, now)
    if approve and approval.requested_expires_at <= now:
        raise SessionConflict("pending approval lifetime expired")


def require_eligible_base(
    base: SessionState, approval: ElevationRequest, project_uuid: UUID, now: datetime
) -> None:
    if (
        base.project_uuid != project_uuid
        or base.status != "active"
        or base.hard_expires_at <= now
        or base.is_elevated
        or base.elevation_policy != "requestable"
        or base.created_by_principal_uuid != approval.requested_by_user_uuid
    ):
        raise SessionAccessDenied("base AgentSession no longer eligible")


def allowed_resolution_operations(
    requested: tuple[str, ...],
    *,
    valid_stored_operations: bool,
    allowed: tuple[str, ...] | None,
    approve: bool,
) -> tuple[str, ...]:
    if not valid_stored_operations:
        raise SessionAccessDenied("invalid stored operation request")
    actual = tuple(sorted(allowed if allowed is not None else requested))
    if approve and (not actual or not set(actual).issubset(requested)):
        raise SessionAccessDenied("approval may not expand original request")
    return actual


def valid_operation_request(raw: tuple[str, ...] | None) -> bool:
    return (
        raw is not None
        and bool(raw)
        and len(set(raw)) == len(raw)
        and set(raw).issubset(SUPPORTED_GRANTS)
    )


def require_revocable_session(state: SessionState, expected_revision: int) -> None:
    if state.version != expected_revision:
        raise SessionConflict("AgentSession revision changed")
    if state.status != "active":
        raise SessionConflict("AgentSession already revoked")


def require_child_session(child: SessionState | None, parent: SessionState) -> SessionState:
    if (
        child is None
        or child.project_uuid != parent.project_uuid
        or child.created_by_principal_uuid != parent.created_by_principal_uuid
        or child.is_elevated is not True
    ):
        raise SessionAccessDenied("inconsistent elevated AgentSession ownership")
    return child
