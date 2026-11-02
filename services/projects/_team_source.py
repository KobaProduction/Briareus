"""Legacy state specialization of its canonical Platform Control commands."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_team_contracts import (
    SignedTeamProofs,
    TeamMemberPayload,
    TeamOwnerCommandDTO,
    TeamOwnerTransferPayload,
    VerifiedTeamOperation,
)
from common.owner_transactions import OwnerCommandOutcome
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects.application.team_receipts import TeamMembershipChanged, TeamOwnerTransferred
from projects.control._team_source import (
    TeamOwnerSource as _TeamOwnerSource,
)
from teams._persistence import TeamMembershipRow, TeamRow


class TeamOwnerSource(_TeamOwnerSource):
    @staticmethod
    async def _owner_team(
        tx: AsyncSession,
        command: TeamOwnerCommandDTO,
        decision: VerifiedTeamOperation,
    ) -> TeamRow:
        team = await tx.scalar(
            select(TeamRow).where(TeamRow.id == command.team_id).with_for_update()
        )
        if team is None or team.version != command.expected_team_revision:
            raise Conflict("Team owner revision does not match signed current authority")
        if decision.actor_role != "superuser" and team.owner_user_id != command.caller_user_id:
            raise AccessDenied("only current Team owner may manage Team membership")
        return team

    async def add_member(
        self, command: TeamOwnerCommandDTO, proofs: SignedTeamProofs, *, target: UUID
    ) -> OwnerCommandOutcome[TeamMembershipChanged]:
        if command.operation != "team.member.add" or target.version != 4:
            raise InvalidInput("Team add-member requires signed active User UUID")
        self.authority.check_payload(command, TeamMemberPayload(target_user_id=str(target)))
        target_revision = await self._target_enabled(command, target)

        async def mutation(
            tx: AsyncSession, decision: VerifiedTeamOperation
        ) -> TeamMembershipChanged:
            team = await self._owner_team(tx, command, decision)
            if await self._target_enabled(command, target) != target_revision:
                raise AccessDenied("target Identity revision changed before Team membership commit")
            member = await tx.scalar(
                select(TeamMembershipRow)
                .where(
                    TeamMembershipRow.team_id == team.id,
                    TeamMembershipRow.user_id == target,
                )
                .with_for_update()
            )
            if member is None:
                member = TeamMembershipRow(team_id=team.id, user_id=target, active=True, version=1)
                tx.add(member)
            elif member.active:
                raise Conflict("Team member already active")
            else:
                member.active = True
                member.version += 1
            team.version += 1
            team.resource_revision += 1
            return TeamMembershipChanged(
                team_id=str(team.id),
                member_user_id=str(target),
                team_version=team.version,
                membership_version=member.version,
                resource_revision=team.resource_revision,
                active=True,
            )

        return await self._execute(
            command,
            proofs,
            mutation,
            event="team.member_added",
            subject=target,
            response_model=TeamMembershipChanged,
        )

    async def remove_member(
        self, command: TeamOwnerCommandDTO, proofs: SignedTeamProofs, *, target: UUID
    ) -> OwnerCommandOutcome[TeamMembershipChanged]:
        if command.operation != "team.member.remove" or target.version != 4:
            raise InvalidInput("Team remove-member requires original User UUID")
        self.authority.check_payload(command, TeamMemberPayload(target_user_id=str(target)))

        async def mutation(
            tx: AsyncSession, decision: VerifiedTeamOperation
        ) -> TeamMembershipChanged:
            team = await self._owner_team(tx, command, decision)
            if team.owner_user_id == target:
                raise AccessDenied("current Team owner cannot be removed")
            member = await tx.scalar(
                select(TeamMembershipRow)
                .where(
                    TeamMembershipRow.team_id == team.id,
                    TeamMembershipRow.user_id == target,
                )
                .with_for_update()
            )
            if member is None or not member.active:
                raise Conflict("Team membership is already inactive or absent")
            member.active = False
            member.version += 1
            team.version += 1
            team.resource_revision += 1
            return TeamMembershipChanged(
                team_id=str(team.id),
                member_user_id=str(target),
                team_version=team.version,
                membership_version=member.version,
                resource_revision=team.resource_revision,
                active=False,
            )

        return await self._execute(
            command,
            proofs,
            mutation,
            event="team.member_removed",
            subject=target,
            response_model=TeamMembershipChanged,
        )

    async def transfer_owner(
        self,
        command: TeamOwnerCommandDTO,
        proofs: SignedTeamProofs,
        *,
        target: UUID,
        confirmed: bool,
    ) -> OwnerCommandOutcome[TeamOwnerTransferred]:
        if command.operation != "team.owner.transfer" or target.version != 4 or not confirmed:
            raise InvalidInput("Team owner transfer needs current User and explicit confirmation")
        self.authority.check_payload(
            command, TeamOwnerTransferPayload(target_user_id=str(target), confirmed=True)
        )
        target_revision = await self._target_enabled(command, target)

        async def mutation(
            tx: AsyncSession, decision: VerifiedTeamOperation
        ) -> TeamOwnerTransferred:
            team = await self._owner_team(tx, command, decision)
            if team.owner_user_id == target:
                raise Conflict("target is already Team owner")
            member = await tx.scalar(
                select(TeamMembershipRow)
                .where(
                    TeamMembershipRow.team_id == team.id,
                    TeamMembershipRow.user_id == target,
                    TeamMembershipRow.active.is_(True),
                )
                .with_for_update()
            )
            if member is None or await self._target_enabled(command, target) != target_revision:
                raise AccessDenied("Team successor must be currently active Identity and member")
            team.owner_user_id = target
            team.version += 1
            team.resource_revision += 1
            return TeamOwnerTransferred(
                team_id=str(team.id),
                owner_user_id=str(target),
                team_version=team.version,
                resource_revision=team.resource_revision,
            )

        return await self._execute(
            command,
            proofs,
            mutation,
            event="team.owner_transferred",
            subject=target,
            response_model=TeamOwnerTransferred,
        )
