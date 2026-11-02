"""One serialized negative fact across every current Platform-owned table."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_registry import owner_metadata
from common.platform_db import PlatformDatabase
from projects._control_ledger import OwnerAuditRow, OwnerOutboxRow
from projects._current_state import project_state
from projects._persistence import ProjectRow
from projects._rauthy_user_links import RauthyUserLinkRow
from projects.application.bootstrap import BootstrapTransaction
from projects.domain.bootstrap import (
    FirstOperatorBootstrapDenied,
    FirstOperatorBootstrapUnavailable,
    VerifiedFirstOperatorApproval,
)
from projects.infrastructure.audit_records import FirstOperatorAudit, FirstOperatorWorkspaceAudit
from projects.infrastructure.owner_event_records import (
    OperatorBootstrapped,
    OperatorWorkspaceCreated,
)
from service_runtime.platform_db_mechanics import (
    _PrivateDatabaseBinding,
    _SessionBinding,
)


class SqlBootstrapUnitOfWork(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[BootstrapTransaction]:
        async with self._database.transaction() as tx:
            yield SqlBootstrapTransaction(tx)


class SqlBootstrapTransaction(_SessionBinding[AsyncSession]):
    async def lock(self) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(:namespace, :lock_id)"),
            {"namespace": 146536, "lock_id": 1},
        )

    async def require_empty(self) -> None:
        tables = tuple(owner_metadata("platform").sorted_tables)
        names = {table.fullname for table in tables}
        if (
            not tables
            or not {"control.rauthy_user_links", "projects.projects", "teams.teams"} <= names
        ):
            raise FirstOperatorBootstrapUnavailable("Platform owner schema unavailable")
        for table in tables:
            if await self._session.scalar(select(1).select_from(table).limit(1)) is not None:
                raise FirstOperatorBootstrapDenied(
                    "first operator requires wholly empty Platform owner"
                )

    async def create(self, approval: VerifiedFirstOperatorApproval, now: datetime) -> None:
        row = RauthyUserLinkRow(
            user_id=approval.user_uuid,
            issuer=approval.rauthy_issuer,
            subject=approval.rauthy_subject,
            briareus_role="operator",
            active=True,
            version=1,
            created_at=now,
            updated_at=now,
        )
        project = ProjectRow(
            id=approval.bootstrap_project_uuid,
            name=approval.bootstrap_project_name,
            lifecycle_status="active",
            owner_user_id=approval.user_uuid,
            owner_team_id=None,
            resource_revision=0,
            created_at=now,
        )
        self._session.add(row)
        self._session.add(project)
        await self._session.flush()
        self._record(approval, project)

    def _record(self, approval: VerifiedFirstOperatorApproval, project: ProjectRow) -> None:
        self._session.add(
            OwnerAuditRow(
                operation_uuid=approval.operation_uuid,
                actor_user_id=None,
                project_id=None,
                action="user.first_operator_bootstrapped",
                object_id=str(approval.user_uuid),
                owner_revision="rauthy-link-v1",
                details=FirstOperatorAudit(),
            )
        )
        revision = format(project_state(project), "064x")
        self._session.add(
            OwnerAuditRow(
                operation_uuid=approval.operation_uuid,
                actor_user_id=None,
                project_id=project.id,
                action="project.first_operator_workspace_bootstrapped",
                object_id=str(project.id),
                owner_revision=revision,
                details=FirstOperatorWorkspaceAudit(owner_user_id=approval.user_uuid),
            )
        )
        self._session.add(
            OwnerOutboxRow(
                operation_uuid=approval.operation_uuid,
                event_name="project.first_operator_workspace_bootstrapped",
                owner_revision=revision,
                event_payload=OperatorWorkspaceCreated(
                    project_id=project.id, owner_user_id=approval.user_uuid
                ),
            )
        )
        self._session.add(
            OwnerOutboxRow(
                operation_uuid=approval.operation_uuid,
                event_name="user.first_operator_bootstrapped",
                owner_revision="rauthy-link-v1",
                event_payload=OperatorBootstrapped(user_id=approval.user_uuid, revision=1),
            )
        )
