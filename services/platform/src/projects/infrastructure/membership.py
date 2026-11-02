"""Current Platform ownership selectors, bounded independently of inventory."""

from uuid import UUID

from sqlalchemy import and_, literal, or_, select, true

from common.platform_db import PlatformDatabase
from projects._persistence import ProjectRow
from projects.domain.membership import (
    CurrentRauthyUserLink,
    MembershipFacts,
    PlatformTeamMembership,
    ProjectOwnership,
)
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding
from teams._persistence import TeamMembershipRow, TeamRow

_MAX_VISIBLE = 100


class SqlMembershipReader(_PrivateDatabaseBinding[PlatformDatabase]):
    async def directory(self, actor: CurrentRauthyUserLink) -> MembershipFacts:
        async with self._database.transaction() as session:
            rows = (
                await session.execute(
                    select(TeamRow, TeamMembershipRow)
                    .outerjoin(
                        TeamMembershipRow,
                        and_(
                            TeamMembershipRow.team_id == TeamRow.id,
                            TeamMembershipRow.user_id == actor.user_id,
                            TeamMembershipRow.active.is_(True),
                        ),
                    )
                    .where(
                        or_(
                            literal(actor.role == "operator"),
                            TeamMembershipRow.user_id == actor.user_id,
                        ),
                    )
                    .order_by(TeamRow.id)
                    .limit(_MAX_VISIBLE + 1)
                )
            ).all()
            if len(rows) > _MAX_VISIBLE:
                return MembershipFacts((), (), True)
            teams = tuple(
                PlatformTeamMembership(
                    team.id,
                    team.owner_user_id == actor.user_id,
                    team.name,
                    member is not None,
                )
                for team, member in rows
            )
            ownership_filter = or_(
                ProjectRow.owner_user_id == actor.user_id,
                ProjectRow.owner_team_id.in_(tuple(team.team_id for team in teams)),
            )
            projects = tuple(
                await session.scalars(
                    select(ProjectRow)
                    .where(
                        true() if actor.role == "operator" else ownership_filter,
                        ProjectRow.lifecycle_status == "active",
                    )
                    .order_by(ProjectRow.id)
                    .limit(_MAX_VISIBLE + 1)
                )
            )
            if len(projects) > _MAX_VISIBLE:
                return MembershipFacts((), (), True)
            return MembershipFacts(teams, tuple(project_ownership(project) for project in projects))

    async def project(
        self, actor: CurrentRauthyUserLink, project_uuid: UUID
    ) -> MembershipFacts | None:
        async with self._database.transaction() as session:
            row = (
                await session.execute(
                    select(ProjectRow, TeamRow, TeamMembershipRow)
                    .outerjoin(
                        TeamRow,
                        TeamRow.id == ProjectRow.owner_team_id,
                    )
                    .outerjoin(
                        TeamMembershipRow,
                        and_(
                            TeamMembershipRow.team_id == TeamRow.id,
                            TeamMembershipRow.user_id == actor.user_id,
                            TeamMembershipRow.active.is_(True),
                        ),
                    )
                    .where(
                        ProjectRow.id == project_uuid,
                        ProjectRow.lifecycle_status == "active",
                        or_(
                            literal(actor.role == "operator"),
                            ProjectRow.owner_user_id == actor.user_id,
                            TeamMembershipRow.user_id == actor.user_id,
                        ),
                    )
                )
            ).one_or_none()
            if row is None:
                return None
            project, team, member = row
            teams = (
                ()
                if team is None
                else (
                    PlatformTeamMembership(
                        team.id,
                        team.owner_user_id == actor.user_id,
                        team.name,
                        member is not None,
                    ),
                )
            )
            return MembershipFacts(teams, (project_ownership(project),))


def project_ownership(row: ProjectRow) -> ProjectOwnership:
    return ProjectOwnership(row.id, row.name, row.owner_user_id, row.owner_team_id)
