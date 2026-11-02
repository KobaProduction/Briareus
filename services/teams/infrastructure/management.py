"""Bind Team stores to the existing transaction without exposing ORM inward."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import TeamId, UserId
from teams.application import TargetUserPort, TeamAuditPort, TeamManagement
from teams.domain import Team, TeamMembership, TeamResourceMissing

from .persistence import TeamMembershipRow, TeamRow
from .repository import TeamRepository, to_team


class SqlTeamStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._repository = TeamRepository()
        self._locked: dict[UUID, TeamRow] = {}

    async def get(self, team_uuid: UUID, *, lock: bool = False) -> Team | None:
        row = await self._repository.get(self._session, TeamId(team_uuid), lock=lock)
        if row is None:
            return None
        if lock:
            self._locked[team_uuid] = row
        return to_team(row)

    async def create(self, name: str, owner_uuid: UUID) -> Team:
        row = TeamRow(id=uuid4(), name=name, owner_user_id=owner_uuid, version=1)
        self._session.add(row)
        await self._session.flush()
        self._session.add(
            TeamMembershipRow(
                id=uuid4(), team_id=row.id, user_id=owner_uuid, active=True, version=1
            )
        )
        return to_team(row)

    async def list_all(self) -> list[Team]:
        rows = await self._session.scalars(select(TeamRow).order_by(TeamRow.name, TeamRow.id))
        return [to_team(row) for row in rows]

    async def list_for_user(self, user_uuid: UUID) -> list[Team]:
        return await self._repository.list_for_user(self._session, UserId(user_uuid))

    async def list_members(self, team_uuid: UUID) -> list[TeamMembership]:
        return await self._repository.list_members(self._session, TeamId(team_uuid))

    async def active_member(self, team_uuid: UUID, user_uuid: UUID) -> bool:
        return await self._repository.active_member(
            self._session, TeamId(team_uuid), UserId(user_uuid)
        )

    async def change_membership(self, team_uuid: UUID, user_uuid: UUID, *, active: bool) -> bool:
        member = await self._repository.member_row(
            self._session, TeamId(team_uuid), UserId(user_uuid)
        )
        if member is None:
            if not active:
                raise TeamResourceMissing("member not found")
            self._session.add(
                TeamMembershipRow(
                    id=uuid4(), team_id=team_uuid, user_id=user_uuid, active=True, version=1
                )
            )
            return True
        if member.active == active:
            return False
        member.active = active
        member.version += 1
        return True

    def save(self, team: Team) -> None:
        row = self._locked[team.id]
        row.owner_user_id = team.owner_user_id
        row.version = team.version


def bind_team_management(
    session: AsyncSession, *, target_users: TargetUserPort, audit: TeamAuditPort
) -> TeamManagement:
    """Bind only this transaction; authentication stays with the outer caller."""
    return TeamManagement(SqlTeamStore(session), target_users, audit)
