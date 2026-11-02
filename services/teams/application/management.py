"""Team transitions orchestrated against caller-bound transaction ports."""

from dataclasses import replace
from uuid import UUID

from common.platform_ids import TeamId, UserId
from teams.domain import (
    Team,
    TeamAccessDenied,
    TeamConflict,
    TeamMembership,
    TeamResourceMissing,
    require_team_owner,
)
from teams.domain.policies import require_removable_member, require_team_version, team_name

from .contracts import CreateTeam, MutateMember, TeamActor, TeamAudit, TransferOwner
from .ports import TargetUserPort, TeamAuditPort, TeamStore


class TeamManagement:
    """The outer caller verifies/locks the actor before invoking a use case."""

    def __init__(
        self, store: TeamStore, target_users: TargetUserPort, audit: TeamAuditPort
    ) -> None:
        self._store = store
        self._target_users = target_users
        self._audit = audit

    async def create_team(self, actor: TeamActor, command: CreateTeam) -> Team:
        team = await self._store.create(team_name(command.name), actor.user_uuid)
        self._audit.record(TeamAudit(actor.user_uuid, "team.created", team.id))
        return team

    async def visible_teams(self, actor: TeamActor) -> list[Team]:
        if actor.is_operator:
            self._audit.record(TeamAudit(actor.user_uuid, "operator.teams_read", "teams"))
            return await self._store.list_all()
        return await self._store.list_for_user(actor.user_uuid)

    async def team_members(self, actor: TeamActor, team_uuid: UUID) -> list[TeamMembership]:
        team = await self._store.get(team_uuid)
        if team is None or (
            not actor.is_operator
            and not await self._store.active_member(team_uuid, actor.user_uuid)
        ):
            raise TeamAccessDenied("Team access denied")
        if actor.is_operator:
            self._audit.record(TeamAudit(actor.user_uuid, "operator.team_members_read", team_uuid))
        return await self._store.list_members(team_uuid)

    async def _writable_team(
        self, actor: TeamActor, team_uuid: UUID, expected_version: int
    ) -> Team:
        team = await self._store.get(team_uuid, lock=True)
        if team is None:
            raise TeamAccessDenied("Team access denied")
        require_team_version(team, expected_version)
        if not actor.is_operator:
            require_team_owner(team, UserId(actor.user_uuid))
        return team

    async def add_team_member(self, actor: TeamActor, command: MutateMember) -> TeamMembership:
        team = await self._writable_team(actor, command.team_uuid, command.expected_version)
        if not await self._target_users.enabled(command.user_uuid):
            raise TeamResourceMissing("User is not active")
        if await self._store.change_membership(command.team_uuid, command.user_uuid, active=True):
            self._store.save(replace(team, version=team.version + 1))
            self._audit.record(
                TeamAudit(actor.user_uuid, "team.member_added", command.user_uuid, team.id)
            )
        return TeamMembership(TeamId(command.team_uuid), UserId(command.user_uuid), True)

    async def remove_team_member(self, actor: TeamActor, command: MutateMember) -> TeamMembership:
        team = await self._writable_team(actor, command.team_uuid, command.expected_version)
        require_removable_member(team, UserId(command.user_uuid))
        if await self._store.change_membership(command.team_uuid, command.user_uuid, active=False):
            self._store.save(replace(team, version=team.version + 1))
            self._audit.record(
                TeamAudit(actor.user_uuid, "team.member_removed", command.user_uuid, team.id)
            )
        return TeamMembership(TeamId(command.team_uuid), UserId(command.user_uuid), False)

    async def transfer_team_owner(self, actor: TeamActor, command: TransferOwner) -> Team:
        team = await self._writable_team(actor, command.team_uuid, command.expected_version)
        if not await self._store.active_member(command.team_uuid, command.new_owner_uuid):
            raise TeamConflict("new owner must be an active Team member")
        if not await self._target_users.enabled(command.new_owner_uuid):
            raise TeamConflict("new owner must be an enabled User")
        if team.owner_user_id == command.new_owner_uuid:
            return team
        transferred = replace(
            team, owner_user_id=UserId(command.new_owner_uuid), version=team.version + 1
        )
        self._store.save(transferred)
        self._audit.record(
            TeamAudit(
                actor.user_uuid,
                "team.owner_transferred",
                team.id,
                new_owner_uuid=command.new_owner_uuid,
            )
        )
        return transferred
