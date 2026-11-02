"""SQL read model; foreign aggregates are represented by UUID only."""

from typing import Protocol

from sqlalchemy import and_, or_, select

from common.platform_db import PlatformDatabase
from projects._oidc_membership_projection import CurrentRauthyUserLink
from projects._persistence import ProjectRow
from projects.application.directory import DirectoryQuery
from projects.domain.directory import (
    DirectoryActor,
    DirectoryItem,
    DirectoryPermission,
    DirectoryProject,
    DirectoryTeam,
)
from projects.domain.ownership import ProjectOwner
from projects.infrastructure._projection_binding import _ProjectionBinding
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding
from teams._persistence import TeamMembershipRow, TeamRow


class CurrentLinkProjection(Protocol):
    async def _current_link(self, *, issuer: str, subject: str) -> CurrentRauthyUserLink | None: ...


class ProjectionDirectoryAuthority(_ProjectionBinding[CurrentLinkProjection]):
    async def current(self, issuer: str, subject: str) -> DirectoryActor | None:
        link = await self._projection._current_link(issuer=issuer, subject=subject)
        return None if link is None else DirectoryActor(link.user_id, link.role, link.expires_at)


class SqlDirectoryReader(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(self, query: DirectoryQuery, actor: DirectoryActor) -> tuple[DirectoryItem, ...]:
        if query.kind == "teams":
            return await self._teams(query, actor)
        return await self._projects(query, actor)

    async def _teams(
        self, query: DirectoryQuery, actor: DirectoryActor
    ) -> tuple[DirectoryTeam, ...]:
        statement = select(TeamRow, TeamMembershipRow).outerjoin(
            TeamMembershipRow,
            and_(
                TeamMembershipRow.team_id == TeamRow.id,
                TeamMembershipRow.user_id == actor.user_id,
                TeamMembershipRow.active.is_(True),
            ),
        )
        if actor.role != "operator":
            statement = statement.where(TeamMembershipRow.user_id == actor.user_id)
        if query.cursor is not None:
            statement = statement.where(TeamRow.id > query.cursor)
        async with self._database.transaction() as tx:
            rows = (await tx.execute(statement.order_by(TeamRow.id).limit(query.limit + 1))).all()
            return tuple(
                DirectoryTeam(
                    team.id, team.name, team.owner_user_id == actor.user_id, member is not None
                )
                for team, member in rows
            )

    async def _projects(
        self, query: DirectoryQuery, actor: DirectoryActor
    ) -> tuple[DirectoryProject, ...]:
        memberships = select(TeamMembershipRow.team_id).where(
            TeamMembershipRow.user_id == actor.user_id,
            TeamMembershipRow.active.is_(True),
        )
        statement = (
            select(ProjectRow, TeamRow)
            .outerjoin(TeamRow, TeamRow.id == ProjectRow.owner_team_id)
            .where(
                ProjectRow.lifecycle_status == "active",
            )
        )
        if actor.role != "operator":
            statement = statement.where(
                or_(
                    ProjectRow.owner_user_id == actor.user_id,
                    ProjectRow.owner_team_id.in_(memberships),
                )
            )
        if query.cursor is not None:
            statement = statement.where(ProjectRow.id > query.cursor)
        async with self._database.transaction() as tx:
            rows = (
                await tx.execute(statement.order_by(ProjectRow.id).limit(query.limit + 1))
            ).all()
            return tuple(project_item(project, team, actor) for project, team in rows)


def project_item(
    project: ProjectRow, team: TeamRow | None, actor: DirectoryActor
) -> DirectoryProject:
    permissions: tuple[DirectoryPermission, ...] = ("use_resources",)
    if actor.can_approve(project.owner_user_id, None if team is None else team.owner_user_id):
        permissions = ("use_resources", "approve_agent_session")
    owner = ProjectOwner.from_ids(project.owner_user_id, project.owner_team_id)
    return DirectoryProject(project.id, project.name, owner, permissions)
