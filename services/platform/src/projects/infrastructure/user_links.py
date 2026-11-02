"""The exact subject binding and public role-change facts commit together."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from projects._control_ledger import OwnerAuditRow, OwnerOutboxRow
from projects._rauthy_user_links import RauthyUserLinkRow
from projects.application.user_links import UserLinkTransaction
from projects.domain.membership import PlatformSubjectLinkUnavailable
from projects.domain.user_links import PlatformRole, PlatformUserLink, ProvisioningAction
from projects.infrastructure.audit_records import RauthyUserLinkedAudit
from projects.infrastructure.owner_event_records import EntityChangedEvent
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


class SqlUserLinkUnitOfWork(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[UserLinkTransaction]:
        async with self._database.transaction() as tx:
            yield SqlUserLinkTransaction(tx)


class SqlUserLinkTransaction:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._row: RauthyUserLinkRow | None = None

    async def lock_subject(self, issuer: str, subject: str) -> None:
        await self._session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:subject,0))"),
            {"subject": issuer + "\n" + subject},
        )

    async def get(self, issuer: str, subject: str) -> PlatformUserLink | None:
        row = await self._session.scalar(
            select(RauthyUserLinkRow)
            .where(
                RauthyUserLinkRow.issuer == issuer,
                RauthyUserLinkRow.subject == subject,
            )
            .with_for_update()
        )
        self._row = row
        if row is None:
            return None
        if row.briareus_role not in {"user", "operator"}:
            raise PlatformSubjectLinkUnavailable("Platform user role invalid")
        role: PlatformRole = "operator" if row.briareus_role == "operator" else "user"
        return PlatformUserLink(
            row.user_id,
            row.issuer,
            row.subject,
            role,
            row.active,
            row.version,
            row.created_at,
            row.updated_at,
        )

    async def save(
        self,
        link: PlatformUserLink,
        operation_uuid: UUID,
        action: ProvisioningAction,
    ) -> None:
        row = self._row
        if row is None:
            row = RauthyUserLinkRow(
                user_id=link.uuid,
                issuer=link.issuer,
                subject=link.subject,
                briareus_role=link.role,
                active=link.active,
                version=link.revision,
                created_at=link.created_at,
                updated_at=link.updated_at,
            )
            self._session.add(row)
            self._row = row
        else:
            row.briareus_role, row.version, row.updated_at = (
                link.role,
                link.revision,
                link.updated_at,
            )
        self._session.add(
            OwnerAuditRow(
                id=operation_uuid,
                operation_uuid=operation_uuid,
                actor_user_id=link.uuid,
                project_id=None,
                action=action,
                object_id=str(link.uuid),
                owner_revision="rauthy-login-v1",
                details=RauthyUserLinkedAudit(
                    issuer=link.issuer, subject=link.subject, role=link.role
                ),
            )
        )
        self._session.add(
            OwnerOutboxRow(
                operation_uuid=operation_uuid,
                event_name=action,
                owner_revision="rauthy-login-v1",
                event_payload=EntityChangedEvent(id=link.uuid),
            )
        )
        await self._session.flush()
