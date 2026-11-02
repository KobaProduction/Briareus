"""Legacy state specialization of its canonical Platform Control commands."""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import SignedOwnerProofs, VerifiedOwnerOperation, require_signed_payload
from common.owner_transactions import OwnerCommandOutcome
from common.platform_errors import AccessDenied, Conflict, InvalidInput
from projects._persistence import ProjectRow
from projects.application.owner_receipts import (
    ControlConfirmProjectDelete,
    ControlMovePersonalToTeam,
    ControlPrepareProjectDelete,
    ControlWithdrawTeamProject,
)
from projects.control._command_payloads import (
    ConfirmProjectDeletePayload,
    MovePersonalToTeamPayload,
    PrepareProjectDeletePayload,
    WithdrawTeamProjectPayload,
)
from projects.control._control_source import (
    ControlSourceService as _ControlSourceService,
)
from projects.control._control_source import (
    TrustedProjectDeleteImpactPort as TrustedProjectDeleteImpactPort,
)
from projects.control._control_source import (
    VerifiedProjectDeleteImpact as VerifiedProjectDeleteImpact,
)
from teams._persistence import TeamMembershipRow, TeamRow


class ControlSourceService(_ControlSourceService):
    @staticmethod
    async def _project(tx: AsyncSession, decision: VerifiedOwnerOperation) -> ProjectRow:
        request = decision.request
        row = await tx.scalar(
            select(ProjectRow).where(ProjectRow.id == request.project_id).with_for_update()
        )
        if (
            row is None
            or row.version != request.expected_control_revision
            or row.lifecycle_status != "active"
        ):
            raise Conflict("active Project ownership revision unavailable or changed")
        return row

    async def move_personal_to_team(
        self, decision: VerifiedOwnerOperation, proofs: SignedOwnerProofs, *, team_id: UUID
    ) -> OwnerCommandOutcome[ControlMovePersonalToTeam]:
        if decision.request.operation != "project.transfer_to_team" or team_id.version != 4:
            raise InvalidInput("transfer requires reviewed Project and Team UUID")
        require_signed_payload(
            decision.request, asdict(MovePersonalToTeamPayload(team_id=str(team_id)))
        )

        async def mutate(tx: AsyncSession) -> ControlMovePersonalToTeam:
            project = await self._project(tx, decision)
            actor = decision.request.caller_user_id
            if project.owner_user_id != actor and decision.actor_role != "superuser":
                raise AccessDenied("only personal Project owner may move a Project")
            if project.owner_team_id is not None:
                raise Conflict("Team Project cannot be inserted into another Team")
            team = await tx.get(TeamRow, team_id, with_for_update=True)
            membership = await tx.scalar(
                select(TeamMembershipRow.id)
                .where(
                    TeamMembershipRow.team_id == team_id,
                    TeamMembershipRow.user_id == actor,
                    TeamMembershipRow.active.is_(True),
                )
                .with_for_update()
            )
            if team is None or membership is None:
                raise AccessDenied("recipient Team current membership unavailable")
            project.owner_user_id = None
            project.owner_team_id = team_id
            project.version += 1
            project.resource_revision += 1
            return ControlMovePersonalToTeam(
                project_id=str(project.id),
                owner_team_id=str(team_id),
                version=project.version,
                resource_revision=project.resource_revision,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutate,
            event="project.transferred_to_team",
            target=str(decision.request.project_id),
            response_model=ControlMovePersonalToTeam,
        )

    async def withdraw_team_project(
        self, decision: VerifiedOwnerOperation, proofs: SignedOwnerProofs
    ) -> OwnerCommandOutcome[ControlWithdrawTeamProject]:
        if decision.request.operation != "project.withdraw_from_team":
            raise InvalidInput("unexpected operation")
        require_signed_payload(decision.request, asdict(WithdrawTeamProjectPayload()))

        async def mutate(tx: AsyncSession) -> ControlWithdrawTeamProject:
            project = await self._project(tx, decision)
            if project.owner_team_id is None:
                raise Conflict("Project is not Team-owned")
            team = await tx.get(TeamRow, project.owner_team_id, with_for_update=True)
            if team is None or (
                team.owner_user_id != decision.request.caller_user_id
                and decision.actor_role != "superuser"
            ):
                raise AccessDenied("only current Team owner can withdraw Project")
            project.owner_user_id = team.owner_user_id
            project.owner_team_id = None
            project.version += 1
            project.resource_revision += 1
            return ControlWithdrawTeamProject(
                project_id=str(project.id),
                owner_user_id=str(team.owner_user_id),
                version=project.version,
                resource_revision=project.resource_revision,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutate,
            event="project.withdrawn_from_team",
            target=str(decision.request.project_id),
            response_model=ControlWithdrawTeamProject,
        )

    async def prepare_project_delete(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        confirmed: bool,
    ) -> OwnerCommandOutcome[ControlPrepareProjectDelete]:
        if decision.request.operation != "project.delete.prepare" or not confirmed:
            raise InvalidInput("Project delete requires an explicit signed prepare confirmation")
        require_signed_payload(
            decision.request, asdict(PrepareProjectDeletePayload(confirmed=True))
        )

        async def mutation(tx: AsyncSession) -> ControlPrepareProjectDelete:
            row = await self._project(tx, decision)
            await self._require_project_owner(tx, decision, row)
            row.lifecycle_status = "deleting"
            row.version += 1
            row.resource_revision += 1
            # THIS IS A FENCE, NOT A FILE/RESOURCE/NATIVE DELETE.
            # Later current Control-issued authorizations deny non-active
            # Projects. Each external owner must durably attest its absence.
            return ControlPrepareProjectDelete(
                project_id=str(row.id),
                lifecycle_status=row.lifecycle_status,
                fenced_control_revision=row.version,
                resource_revision=row.resource_revision,
                reconciliation_required=True,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="project.delete_preparing",
            target=str(decision.request.project_id),
            response_model=ControlPrepareProjectDelete,
        )

    async def confirm_project_delete(
        self,
        decision: VerifiedOwnerOperation,
        proofs: SignedOwnerProofs,
        *,
        fenced_control_revision: int,
    ) -> OwnerCommandOutcome[ControlConfirmProjectDelete]:
        """Finalize Control tombstone only after every durable owner is empty.

        No physical deletion is performed by Control. Native Files/Runtime/
        Reverse/Resource owners retain their own cleanup and backup contracts.
        """
        if (
            decision.request.operation != "project.delete.confirm"
            or fenced_control_revision != decision.request.expected_control_revision
            or self.delete_impact is None
        ):
            raise AccessDenied("Project deletion requires original fence and all signed owners")
        require_signed_payload(
            decision.request,
            asdict(ConfirmProjectDeletePayload(fenced_control_revision=fenced_control_revision)),
        )
        verified = await self._current_deletion_impacts(
            self.delete_impact, decision, fenced_control_revision
        )

        async def mutation(tx: AsyncSession) -> ControlConfirmProjectDelete:
            row = await tx.scalar(
                select(ProjectRow)
                .where(ProjectRow.id == decision.request.project_id)
                .with_for_update()
            )
            if (
                row is None
                or row.lifecycle_status != "deleting"
                or row.version != fenced_control_revision
                or row.resource_revision != decision.request.expected_control_resource_revision
            ):
                raise AccessDenied("Project is not fenced for owner deletion")
            await self._require_project_owner(tx, decision, row)
            if any(
                datetime.now(UTC) - receipt.observed_at > timedelta(seconds=20)
                for receipt in verified
            ):
                raise AccessDenied("owner deletion proof expired while acquiring Control lock")
            row.lifecycle_status = "deleted"
            row.version += 1
            row.resource_revision += 1
            return ControlConfirmProjectDelete(
                project_id=str(row.id),
                lifecycle_status=row.lifecycle_status,
                version=row.version,
                resource_revision=row.resource_revision,
                native_artifacts_removed=False,
                physical_cleanup_verified=False,
            )

        return await self.commands.execute_local(
            decision,
            proofs,
            mutation,
            event="project.delete_finalized",
            target=str(decision.request.project_id),
            response_model=ControlConfirmProjectDelete,
        )
