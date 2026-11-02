"""Public projection of verified authority; never a source of permissions."""

from dataclasses import dataclass
from typing import Literal

from control_panel_api.domain.platform_authority import PanelOidcSession, ResolvedPlatformUser


@dataclass(frozen=True, slots=True)
class RauthySubject:
    issuer: str
    subject: str


@dataclass(frozen=True, slots=True)
class PlatformUser:
    id: str
    role: Literal["user", "operator"]
    enabled: Literal[True]
    name: str | None
    email: str | None


@dataclass(frozen=True, slots=True)
class PlatformTeam:
    id: str
    owner: bool
    name: str | None
    member: bool


@dataclass(frozen=True, slots=True)
class ProjectOwner:
    kind: Literal["user", "team"]
    id: str


@dataclass(frozen=True, slots=True)
class PlatformProject:
    id: str
    name: str | None
    owner: ProjectOwner
    permissions: tuple[Literal["use_resources", "approve_agent_session"], ...]


@dataclass(frozen=True, slots=True)
class PlatformContextPayload:
    authenticated: Literal[True]
    authority: Literal["platform"]
    directory_paged: bool
    rauthy: RauthySubject
    user: PlatformUser
    teams: tuple[PlatformTeam, ...]
    projects: tuple[PlatformProject, ...]
    expires_at: str


def platform_context_payload(
    session: PanelOidcSession, proof: ResolvedPlatformUser
) -> PlatformContextPayload:
    return PlatformContextPayload(
        True,
        "platform",
        proof.directory_paged,
        RauthySubject(proof.issuer, proof.subject),
        PlatformUser(str(proof.user_uuid), proof.role, True, proof.name, proof.email),
        tuple(
            PlatformTeam(str(item.team_uuid), item.owner, item.name, item.member)
            for item in proof.teams
        ),
        tuple(
            PlatformProject(
                str(item.project_uuid),
                item.name,
                ProjectOwner(item.owner_kind, str(item.owner_uuid)),
                item.permissions,
            )
            for item in proof.projects
        ),
        min(proof.expires_at, session.expires_at).isoformat(),
    )
