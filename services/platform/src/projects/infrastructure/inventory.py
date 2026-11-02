"""Bounded Platform inventory SQL read models."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from projects._persistence import ProjectRow
from projects._rauthy_user_links import RauthyUserLinkRow
from projects.application.inventory import InventoryQuery
from projects.domain.inventory import (
    InventoryProject,
    InventorySnapshot,
    InventoryTeam,
    InventoryUserReference,
)
from projects.domain.management import ManagementError
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding
from teams._persistence import TeamMembershipRow, TeamRow


class SqlInventoryReader(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(self, query: InventoryQuery) -> InventorySnapshot:
        async with self._database.transaction() as tx:
            if query.team_uuid is not None:
                return await self._team(tx, query)
            users = tuple(
                await tx.scalars(
                    select(RauthyUserLinkRow)
                    .where(
                        RauthyUserLinkRow.issuer == query.issuer,
                    )
                    .order_by(RauthyUserLinkRow.user_id)
                    .limit(101)
                )
            )
            teams = tuple(
                await tx.scalars(select(TeamRow).order_by(TeamRow.name, TeamRow.id).limit(101))
            )
            projects = tuple(
                await tx.scalars(
                    select(ProjectRow)
                    .where(
                        ProjectRow.lifecycle_status == "active",
                    )
                    .order_by(ProjectRow.name, ProjectRow.id)
                    .limit(101)
                )
            )
            members = tuple(
                await tx.scalars(
                    select(TeamMembershipRow)
                    .where(
                        TeamMembershipRow.team_id.in_([team.id for team in teams[:100]]),
                        TeamMembershipRow.active.is_(True),
                    )
                    .limit(1001)
                )
            )
            return inventory_snapshot(users, teams, projects, members)

    async def _team(self, tx: AsyncSession, query: InventoryQuery) -> InventorySnapshot:
        team = await tx.get(TeamRow, query.team_uuid)
        membership = await tx.scalar(
            select(TeamMembershipRow).where(
                TeamMembershipRow.team_id == query.team_uuid,
                TeamMembershipRow.user_id == query.actor_uuid,
                TeamMembershipRow.active.is_(True),
            )
        )
        if team is None or not (query.operator or membership is not None):
            raise ManagementError(403, "TEAM_MEMBERSHIP_REQUIRED")
        members = tuple(
            await tx.scalars(
                select(TeamMembershipRow)
                .where(
                    TeamMembershipRow.team_id == query.team_uuid,
                    TeamMembershipRow.active.is_(True),
                )
                .limit(101)
            )
        )
        users = tuple(
            await tx.scalars(
                select(RauthyUserLinkRow).where(
                    RauthyUserLinkRow.issuer == query.issuer,
                    RauthyUserLinkRow.user_id.in_([member.user_id for member in members[:100]]),
                )
            )
        )
        projects = tuple(
            await tx.scalars(
                select(ProjectRow)
                .where(
                    ProjectRow.owner_team_id == query.team_uuid,
                    ProjectRow.lifecycle_status == "active",
                )
                .order_by(ProjectRow.name)
                .limit(101)
            )
        )
        return inventory_snapshot(users, (team,), projects, members, member_limit=100)


def inventory_snapshot(
    users: tuple[RauthyUserLinkRow, ...],
    teams: tuple[TeamRow, ...],
    projects: tuple[ProjectRow, ...],
    members: tuple[TeamMembershipRow, ...],
    member_limit: int = 1000,
) -> InventorySnapshot:
    return InventorySnapshot(
        tuple(
            InventoryUserReference(user.user_id, user.subject, user.briareus_role, user.active)
            for user in users[:100]
        ),
        tuple(
            InventoryTeam(
                team.id,
                team.name,
                team.owner_user_id,
                tuple(
                    member.user_id for member in members[:member_limit] if member.team_id == team.id
                ),
            )
            for team in teams[:100]
        ),
        tuple(
            InventoryProject(
                project.id,
                project.name,
                project.owner_user_id,
                project.owner_team_id,
            )
            for project in projects[:100]
        ),
        len(users) > 100 or len(teams) > 100 or len(projects) > 100 or len(members) > member_limit,
    )
