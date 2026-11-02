"""Only a current provider link and current ownership facts grant visibility."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from projects.control.domain.scope_events import _uuid4 as _current_uuid4

valid_uuid4 = _current_uuid4
del _current_uuid4


class PlatformSubjectLinkUnavailable(Exception):
    """Current external-subject/User or ownership authority is unavailable."""


@dataclass(frozen=True, slots=True)
class CurrentRauthyUserLink:
    issuer: str
    subject: str
    user_id: UUID
    enabled: bool
    role: Literal["user", "operator"]
    revision: int
    expires_at: datetime
    name: str | None = None
    email: str | None = None


@dataclass(frozen=True, slots=True)
class PlatformTeamMembership:
    team_id: UUID
    owner: bool
    name: str | None = None
    member: bool = True


@dataclass(frozen=True, slots=True)
class PlatformProjectMembership:
    project_id: UUID
    owner_kind: Literal["user", "team"]
    owner_id: UUID
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]
    name: str | None = None


@dataclass(frozen=True, slots=True)
class CurrentRauthyPlatformMembership:
    issuer: str
    subject: str
    user_id: UUID
    role: Literal["user", "operator"]
    enabled: bool
    expires_at: datetime
    teams: tuple[PlatformTeamMembership, ...]
    projects: tuple[PlatformProjectMembership, ...]
    name: str | None = None
    email: str | None = None
    directory_paged: bool = False


def current_link(
    value: object,
    issuer: str,
    subject: str,
    now: datetime,
) -> CurrentRauthyUserLink | None:
    if not isinstance(value, CurrentRauthyUserLink):
        raise PlatformSubjectLinkUnavailable("signed Rauthy subject link invalid")
    if value.issuer != issuer or value.subject != subject or value.role not in {"user", "operator"}:
        raise PlatformSubjectLinkUnavailable("signed Rauthy subject scope invalid")
    if not valid_uuid4(value.user_id) or type(value.enabled) is not bool:
        raise PlatformSubjectLinkUnavailable("signed Rauthy subject identity invalid")
    if type(value.revision) is not int or value.revision < 1:
        raise PlatformSubjectLinkUnavailable("signed Rauthy subject revision invalid")
    if not valid_link_expiry(value.expires_at, now):
        raise PlatformSubjectLinkUnavailable("signed Rauthy subject link expired")
    return value if value.enabled else None


def valid_link_expiry(value: object, now: datetime) -> bool:
    return (
        isinstance(value, datetime)
        and value.tzinfo is not None
        and now < value <= now + timedelta(seconds=30)
    )


@dataclass(frozen=True, slots=True)
class ProjectOwnership:
    uuid: UUID
    name: str
    owner_user_uuid: UUID | None
    owner_team_uuid: UUID | None

    def membership(
        self,
        actor: CurrentRauthyUserLink,
        teams: tuple[PlatformTeamMembership, ...],
    ) -> PlatformProjectMembership:
        if self.owner_user_uuid is not None and self.owner_team_uuid is None:
            if actor.role != "operator" and self.owner_user_uuid != actor.user_id:
                raise PlatformSubjectLinkUnavailable("foreign personal Project")
            return PlatformProjectMembership(
                self.uuid,
                "user",
                self.owner_user_uuid,
                ("use_resources", "approve_agent_session"),
                self.name,
            )
        team = next((item for item in teams if item.team_id == self.owner_team_uuid), None)
        if (
            self.owner_user_uuid is not None
            or team is None
            or not (actor.role == "operator" or team.member)
        ):
            raise PlatformSubjectLinkUnavailable("Project owner scope invalid")
        permissions: tuple[Literal["use_resources", "approve_agent_session"], ...] = (
            "use_resources",
        )
        if actor.role == "operator" or team.owner:
            permissions = ("use_resources", "approve_agent_session")
        return PlatformProjectMembership(self.uuid, "team", team.team_id, permissions, self.name)


@dataclass(frozen=True, slots=True)
class MembershipFacts:
    teams: tuple[PlatformTeamMembership, ...]
    projects: tuple[ProjectOwnership, ...]
    directory_paged: bool = False

    def for_actor(self, actor: CurrentRauthyUserLink) -> CurrentRauthyPlatformMembership:
        projects = tuple(project.membership(actor, self.teams) for project in self.projects)
        return CurrentRauthyPlatformMembership(
            actor.issuer,
            actor.subject,
            actor.user_id,
            actor.role,
            True,
            actor.expires_at,
            self.teams,
            projects,
            actor.name,
            actor.email,
            self.directory_paged,
        )
