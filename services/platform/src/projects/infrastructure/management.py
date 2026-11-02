"""Platform SQL unit of work; no authorization state escapes the transaction."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from projects._control_ledger import OwnerAuditRow, OwnerOutboxRow
from projects._persistence import ProjectRow
from projects._rauthy_user_links import RauthyUserLinkRow
from projects.application.management import ManagementCommand, ManagementTransaction
from projects.domain.management import (
    ManagedProject,
    ManagedTeam,
    ManagementError,
    ManagementOutcome,
)
from projects.infrastructure.owner_event_records import EntityChangedEvent
from projects.infrastructure.panel_journal import (
    MANAGEMENT_REVISION,
    ManagementEvidence,
    ManagementReceipt,
)
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding
from teams._persistence import TeamMembershipRow, TeamRow


class SqlManagementUnitOfWork(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[ManagementTransaction]:
        async with self._database.transaction() as session:
            yield SqlManagementTransaction(session)


class SqlManagementTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._teams: dict[UUID, TeamRow] = {}
        self._projects: dict[UUID, ProjectRow] = {}

    async def lock_operation(self, operation_uuid: UUID) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:operation, 0))"),
            {"operation": str(operation_uuid)},
        )

    async def require_operator(self, actor_uuid: UUID) -> None:
        link = await self._session.get(RauthyUserLinkRow, actor_uuid, with_for_update=True)
        if link is None or not link.active or link.briareus_role != "operator" or link.version < 1:
            raise ManagementError(403, "PLATFORM_OPERATOR_REQUIRED")

    async def previous(self, command: ManagementCommand) -> ManagementOutcome | None:
        row = await self._session.get(OwnerAuditRow, command.operation_uuid)
        if row is None:
            return None
        try:
            evidence = ManagementEvidence.load(row)
        except ValueError:
            raise ManagementError(409, "OPERATION_CONFLICT") from None
        if row.actor_user_id != command.actor_uuid or evidence.fingerprint != command.fingerprint:
            raise ManagementError(409, "OPERATION_CONFLICT")
        return evidence.outcome.record()

    async def team(self, uuid: UUID) -> ManagedTeam:
        row = await self._session.get(TeamRow, uuid, with_for_update=True)
        if row is None:
            raise ManagementError(404, "TEAM_NOT_FOUND")
        self._teams[uuid] = row
        return ManagedTeam(row.id, row.name, row.owner_user_id, row.resource_revision)

    async def project(self, uuid: UUID) -> ManagedProject:
        row = await self._session.get(ProjectRow, uuid, with_for_update=True)
        if row is None or row.lifecycle_status != "active":
            raise ManagementError(404, "PROJECT_NOT_FOUND")
        self._projects[uuid] = row
        return ManagedProject(row.id, row.name, row.owner_user_id, row.owner_team_id)

    async def require_user(self, issuer: str, user_uuid: UUID) -> None:
        target = await self._session.get(RauthyUserLinkRow, user_uuid)
        if target is None or not target.active or target.issuer != issuer:
            raise ManagementError(404, "USER_NOT_FOUND")

    async def add_team(self, team: ManagedTeam) -> None:
        row = TeamRow(
            id=team.uuid, name=team.name, owner_user_id=team.owner_user_uuid, resource_revision=0
        )
        self._session.add(row)
        self._teams[team.uuid] = row
        await self._session.flush()

    async def save_team(self, team: ManagedTeam) -> None:
        row = self._teams[team.uuid]
        row.name = team.name
        row.resource_revision = team.resource_revision

    async def set_member(self, team_uuid: UUID, user_uuid: UUID, active: bool) -> None:
        member = await self._session.scalar(
            select(TeamMembershipRow)
            .where(
                TeamMembershipRow.team_id == team_uuid,
                TeamMembershipRow.user_id == user_uuid,
            )
            .with_for_update()
        )
        if member is None:
            if not active:
                raise ManagementError(404, "MEMBER_NOT_FOUND")
            self._session.add(
                TeamMembershipRow(id=uuid4(), team_id=team_uuid, user_id=user_uuid, active=True)
            )
        else:
            member.active = active

    async def add_project(self, project: ManagedProject) -> None:
        self._session.add(
            ProjectRow(
                id=project.uuid,
                name=project.name,
                lifecycle_status="active",
                owner_user_id=project.owner_user_uuid,
                owner_team_id=project.owner_team_uuid,
                resource_revision=0,
            )
        )

    async def save_project(self, project: ManagedProject) -> None:
        self._projects[project.uuid].name = project.name

    async def record(self, command: ManagementCommand, outcome: ManagementOutcome) -> None:
        self._session.add(
            OwnerAuditRow(
                id=command.operation_uuid,
                operation_uuid=command.operation_uuid,
                actor_user_id=command.actor_uuid,
                project_id=None,
                action="panel." + command.action,
                object_id=str(outcome.id),
                owner_revision=MANAGEMENT_REVISION,
                details=ManagementEvidence(
                    fingerprint=command.fingerprint,
                    outcome=ManagementReceipt.from_record(outcome),
                ),
            )
        )
        self._session.add(
            OwnerOutboxRow(
                operation_uuid=command.operation_uuid,
                event_name="panel." + command.action,
                owner_revision=MANAGEMENT_REVISION,
                event_payload=EntityChangedEvent(id=outcome.id),
            )
        )
        await self._session.flush()
