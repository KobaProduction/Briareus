"""Short-lived independent peer/subject binding and exact projection invariants."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from control_panel_api.domain.native_login import SecretText
from control_panel_api.domain.platform_authority import ResolvedPlatformUser


class PlatformProjectionInvalid(Exception):
    """Owner evidence is unavailable, malformed, stale or bound to another subject."""


@dataclass(frozen=True, slots=True)
class PlatformProjectionQuery:
    issuer: str
    subject: str
    project_uuid: UUID | None

    def require_selector(self) -> None:
        if self.project_uuid is not None:
            self.require_exact_project()

    def require_exact_project(self) -> None:
        if not isinstance(self.project_uuid, UUID) or self.project_uuid.version != 4:
            raise PlatformProjectionInvalid("invalid exact Platform Project")


@dataclass(frozen=True, slots=True)
class PlatformProjectionAuthority:
    mode: str
    audience: str
    transport_expires_at: datetime
    issuer: str
    subject: str
    project_uuid: UUID | None
    recipient: str
    expires_at: datetime
    bearer: SecretText = field(repr=False)

    def require_current(self, query: PlatformProjectionQuery, now: datetime) -> None:
        transport_current = (
            self.mode in {"mtls", "unix-peer"}
            and self.audience == "briareus:platform"
            and self.transport_expires_at.tzinfo is not None
            and now < self.transport_expires_at <= now + timedelta(seconds=30)
        )
        delegation_current = (
            (self.issuer, self.subject, self.project_uuid)
            == (query.issuer, query.subject, query.project_uuid)
            and self.recipient == "briareus:platform"
            and self.expires_at.tzinfo is not None
        )
        if not transport_current or not delegation_current:
            raise PlatformProjectionInvalid("untrusted Platform peer delegation")
        if not now < self.expires_at <= self.transport_expires_at:
            raise PlatformProjectionInvalid("untrusted Platform peer delegation")
        credential = self.bearer.get_secret_value()
        if (
            not credential
            or len(credential) > 8192
            or not credential.isascii()
            or any(character.isspace() for character in credential)
        ):
            raise PlatformProjectionInvalid("invalid private Platform bearer")


def require_current_projection(
    query: PlatformProjectionQuery,
    current: ResolvedPlatformUser,
    *,
    authority_expires_at: datetime,
    now: datetime,
) -> None:
    identity_current = (
        current.issuer == query.issuer
        and current.subject == query.subject
        and current.enabled
        and current.user_uuid.version == 4
        and current.expires_at.tzinfo is not None
    )
    if not identity_current or not now < current.expires_at <= authority_expires_at:
        raise PlatformProjectionInvalid("Platform response not current")
    if len(current.teams) > 100 or len(current.projects) > 100:
        raise PlatformProjectionInvalid("Platform response not current")
    _require_exact_projection(query, current)
    if any(item.team_uuid.version != 4 for item in current.teams):
        raise PlatformProjectionInvalid("Platform response not current")
    if any(
        item.project_uuid.version != 4 or item.owner_uuid.version != 4 for item in current.projects
    ):
        raise PlatformProjectionInvalid("Platform response not current")


def _require_exact_projection(
    query: PlatformProjectionQuery,
    current: ResolvedPlatformUser,
) -> None:
    if query.project_uuid is None:
        return
    if (
        len(current.projects) != 1
        or len(current.teams) > 1
        or current.projects[0].project_uuid != query.project_uuid
    ):
        raise PlatformProjectionInvalid("Platform response not current")
