"""Private service evidence is independent of the delegated browser subject."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from projects.domain.membership import CurrentRauthyPlatformMembership, valid_uuid4
from projects.domain.membership import valid_link_expiry as _current_expiry

current_expiry = _current_expiry
del _current_expiry


@dataclass(frozen=True, slots=True)
class ContextSelector:
    issuer: str
    subject: str
    project_uuid: UUID | None = None


@dataclass(frozen=True, slots=True)
class VerifiedPanelContextPeer:
    service_audience: Literal["briareus:platform"]
    consumer: Literal["control-panel-api"]
    issuer: str
    subject: str
    expires_at: datetime
    project_uuid: UUID | None = None


@dataclass(frozen=True, slots=True)
class VerifiedAccessProjectPeer:
    audience: Literal["briareus:platform"]
    consumer: Literal["authorization", "resources"]
    issuer: str
    subject: str
    project_uuid: UUID
    expires_at: datetime


def live_expiry(value: object, now: datetime) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None and value > now


def platform_audience(value: object) -> bool:
    return value == "briareus:platform"


def panel_consumer(value: object) -> bool:
    return value == "control-panel-api"


def panel_peer_matches(value: object, selector: ContextSelector, now: datetime) -> bool:
    return (
        isinstance(value, VerifiedPanelContextPeer)
        and platform_audience(value.service_audience)
        and panel_consumer(value.consumer)
        and value.issuer == selector.issuer
        and value.subject == selector.subject
        and value.project_uuid == selector.project_uuid
        and current_expiry(value.expires_at, now)
    )


def access_peer_matches(value: object, selector: ContextSelector, now: datetime) -> bool:
    return (
        isinstance(value, VerifiedAccessProjectPeer)
        and platform_audience(value.audience)
        and value.consumer in {"authorization", "resources"}
        and value.issuer == selector.issuer
        and value.subject == selector.subject
        and value.project_uuid == selector.project_uuid
        and current_expiry(value.expires_at, now)
    )


def membership_matches(value: object, selector: ContextSelector, now: datetime) -> bool:
    if not isinstance(value, CurrentRauthyPlatformMembership):
        return False
    return (
        value.issuer == selector.issuer
        and value.subject == selector.subject
        and valid_uuid4(value.user_id)
        and value.enabled is True
        and value.role in {"user", "operator"}
        and live_expiry(value.expires_at, now)
    )


def exact_project_matches(
    value: CurrentRauthyPlatformMembership, project_uuid: UUID | None
) -> bool:
    return project_uuid is None or (
        len(value.projects) == 1
        and value.projects[0].project_id == project_uuid
        and len(value.teams) <= 1
    )
