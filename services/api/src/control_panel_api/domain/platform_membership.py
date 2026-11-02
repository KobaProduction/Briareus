"""Fresh owner proof and ownership invariants for Control Panel membership."""

from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from control_panel_api.domain.approval_policy import uuid4 as _uuid_v4

from .platform_authority import (
    PanelOidcSession,
    PlatformProjectContext,
    PlatformTeamContext,
    ResolvedPlatformUser,
)


class MembershipProofFailure(StrEnum):
    NOT_CURRENT = "PLATFORM_MEMBERSHIP_NOT_CURRENT"
    INVALID = "PLATFORM_MEMBERSHIP_PROOF_INVALID"


def _aware_datetime(value: object) -> bool:
    return isinstance(value, datetime) and value.tzinfo is not None


def _bounded_tuple(value: object, maximum: int) -> bool:
    return isinstance(value, tuple) and len(value) <= maximum


def _exact_bool(value: object) -> bool:
    return type(value) is bool


def _project_instance(value: object) -> bool:
    return isinstance(value, PlatformProjectContext)


def _identity_current(
    proof: ResolvedPlatformUser, session: PanelOidcSession, now: datetime
) -> bool:
    return (
        proof.issuer == session.issuer
        and proof.subject == session.subject
        and _uuid_v4(proof.user_uuid)
        and proof.enabled is True
        and proof.role in {"user", "operator"}
        and _aware_datetime(proof.expires_at)
        and now < proof.expires_at <= now + timedelta(seconds=30)
        and session.expires_at > now
    )


def _relations_bounded(proof: ResolvedPlatformUser) -> bool:
    return _bounded_tuple(proof.teams, 100) and _bounded_tuple(proof.projects, 100)


def _team_valid(team: object, role: str, seen: set[UUID]) -> bool:
    return (
        isinstance(team, PlatformTeamContext)
        and _uuid_v4(team.team_uuid)
        and team.team_uuid not in seen
        and _exact_bool(team.owner)
        and _exact_bool(team.member)
        and (team.member or role == "operator")
    )


def _project_shape_valid(project: object, seen: set[UUID]) -> bool:
    return (
        isinstance(project, PlatformProjectContext)
        and _uuid_v4(project.project_uuid)
        and _uuid_v4(project.owner_uuid)
        and project.project_uuid not in seen
        and project.owner_kind in {"user", "team"}
        and _bounded_tuple(project.permissions, 2)
        and len(set(project.permissions)) == len(project.permissions)
        and all(item in {"use_resources", "approve_agent_session"} for item in project.permissions)
    )


def _project_owner_valid(
    project: PlatformProjectContext, proof: ResolvedPlatformUser, teams: set[UUID]
) -> bool:
    if project.owner_kind == "team":
        return project.owner_uuid in teams
    return project.owner_uuid == proof.user_uuid or proof.role == "operator"


def _can_approve(project: PlatformProjectContext, proof: ResolvedPlatformUser) -> bool:
    if "approve_agent_session" not in project.permissions or proof.role == "operator":
        return True
    if project.owner_kind == "user":
        return project.owner_uuid == proof.user_uuid
    return any(team.team_uuid == project.owner_uuid and team.owner for team in proof.teams)


def _exact_project(proof: ResolvedPlatformUser, project_uuid: UUID | None) -> bool:
    if project_uuid is None:
        return True
    return (
        len(proof.projects) == 1
        and _project_instance(proof.projects[0])
        and proof.projects[0].project_uuid == project_uuid
        and len(proof.teams) <= 1
    )


def validate_membership_proof(
    session: PanelOidcSession,
    proof: object,
    project_uuid: UUID | None,
    *,
    now: datetime,
) -> MembershipProofFailure | None:
    if (
        not isinstance(proof, ResolvedPlatformUser)
        or not _identity_current(proof, session, now)
        or not _relations_bounded(proof)
    ):
        return MembershipProofFailure.NOT_CURRENT
    if not _exact_project(proof, project_uuid):
        return MembershipProofFailure.INVALID
    seen_teams: set[UUID] = set()
    for team in proof.teams:
        if not _team_valid(team, proof.role, seen_teams):
            return MembershipProofFailure.INVALID
        seen_teams.add(team.team_uuid)
    seen_projects: set[UUID] = set()
    for project in proof.projects:
        if (
            not _project_shape_valid(project, seen_projects)
            or not _project_owner_valid(project, proof, seen_teams)
            or not _can_approve(project, proof)
        ):
            return MembershipProofFailure.INVALID
        seen_projects.add(project.project_uuid)
    return None
