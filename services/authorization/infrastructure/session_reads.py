"""Access-owner SQL snapshots and validation of persisted JSONB grant payloads."""

from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select

from authorization._session_persistence import ProjectAgentSessionRow, SessionApprovalRow
from authorization.application.session_reads import SessionReadQuery
from authorization.domain.session_reads import (
    ApprovalReadEntry,
    SessionReadEntry,
    SessionReadUnavailable,
    VerifiedApprovalActor,
)
from authorization.domain.sessions import SUPPORTED_GRANTS, SessionResourceGrant
from authorization.infrastructure.session_grant_storage import StoredSessionPermissions
from authorization.infrastructure.session_scopes import stored_resources
from common.platform_db import PlatformDatabase
from service_runtime.platform_db_mechanics import _DatabaseBinding


@dataclass(frozen=True, slots=True)
class ReadGrants:
    operations: tuple[str, ...]
    resources: tuple[SessionResourceGrant, ...]


def read_grants(raw: StoredSessionPermissions, project_uuid: UUID) -> ReadGrants:
    operations = raw.operations
    if (
        operations is None
        or not 1 <= len(operations) <= 32
        or not set(operations).issubset(SUPPORTED_GRANTS)
        or len(set(operations)) != len(operations)
    ):
        raise SessionReadUnavailable
    try:
        normalized = stored_resources(
            raw.resources,
            operations,
            project_uuid=project_uuid,
        )
    except ValueError:
        raise SessionReadUnavailable from None
    return ReadGrants(tuple(operations), normalized)


def approval_entry(
    row: SessionApprovalRow, label: str | None, project_uuid: UUID
) -> ApprovalReadEntry:
    grants = read_grants(row.requested_grants, project_uuid)
    return ApprovalReadEntry(
        request_uuid=row.id,
        project_uuid=row.project_id,
        session_uuid=row.session_uuid,
        requested_by_user_uuid=row.requested_by_user_id,
        label=label,
        created_at=row.created_at,
        status=row.status,
        version=row.version,
        operations=grants.operations,
        resources=grants.resources,
        requested_expires_at=row.requested_expires_at,
        resolved_by_user_uuid=row.resolved_by_user_id,
        issued_session_uuid=row.issued_session_uuid,
    )


def session_entry(row: ProjectAgentSessionRow, project_uuid: UUID) -> SessionReadEntry:
    grants = read_grants(row.grants, project_uuid)
    return SessionReadEntry(
        session_uuid=row.session_uuid,
        project_uuid=row.project_id,
        created_by_user_uuid=row.created_by_principal_id,
        label=row.label,
        created_at=row.created_at,
        revision=row.version,
        status=row.status,
        is_elevated=row.is_elevated,
        elevation_policy=row.elevation_policy,
        hard_expires_at=row.hard_expires_at,
        operations=grants.operations,
        resources=grants.resources,
        revoked_at=row.revoked_at,
    )


class SqlSessionReadRepository(_DatabaseBinding[PlatformDatabase]):
    async def approvals(
        self,
        query: SessionReadQuery,
        actor: VerifiedApprovalActor,
    ) -> tuple[ApprovalReadEntry, ...]:
        statement = select(SessionApprovalRow).where(
            SessionApprovalRow.project_id == query.project_uuid
        )
        if not actor.can_approve:
            statement = statement.where(SessionApprovalRow.requested_by_user_id == actor.actor_uuid)
        statement = statement.order_by(
            SessionApprovalRow.created_at.desc(), SessionApprovalRow.id.desc()
        ).limit(query.limit)
        async with self.database.transaction() as tx:
            rows = tuple(await tx.scalars(statement))
            if len(rows) > query.limit:
                raise SessionReadUnavailable
            labels = {
                row.session_uuid: row.label
                for row in await tx.scalars(
                    select(ProjectAgentSessionRow).where(
                        ProjectAgentSessionRow.project_id == query.project_uuid,
                        ProjectAgentSessionRow.session_uuid.in_([row.session_uuid for row in rows]),
                    )
                )
            }
            return tuple(
                approval_entry(row, labels.get(row.session_uuid), query.project_uuid)
                for row in rows
            )

    async def sessions(
        self,
        query: SessionReadQuery,
        actor: VerifiedApprovalActor,
    ) -> tuple[SessionReadEntry, ...]:
        statement = select(ProjectAgentSessionRow).where(
            ProjectAgentSessionRow.project_id == query.project_uuid
        )
        if not actor.can_approve:
            statement = statement.where(
                ProjectAgentSessionRow.created_by_principal_id == actor.actor_uuid
            )
        if query.session_uuid is not None:
            statement = statement.where(ProjectAgentSessionRow.session_uuid == query.session_uuid)
        statement = statement.order_by(
            ProjectAgentSessionRow.created_at.desc(),
            ProjectAgentSessionRow.session_uuid.desc(),
        ).limit(query.limit)
        async with self.database.transaction() as tx:
            rows = tuple(await tx.scalars(statement))
            if len(rows) > query.limit:
                raise SessionReadUnavailable
            return tuple(session_entry(row, query.project_uuid) for row in rows)
