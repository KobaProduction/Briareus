"""Invitation ledger adapter keeps grants, intent, audit and events atomic."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Protocol
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from projects._control_ledger import OwnerAuditRow, OwnerOutboxRow
from projects._oidc_membership_projection import CurrentRauthyPlatformMembership
from projects._rauthy_user_links import RauthyUserLinkRow
from projects.application.invitations import (
    InvitationActor,
    InvitationCommand,
    InvitationIdentity,
    InvitationTransaction,
    IssueInvitation,
    SetInviter,
)
from projects.domain.invitations import (
    InvitationCapabilities,
    InvitationOutcome,
    InvitationResult,
    InviterOutcome,
    ProviderUser,
)
from projects.domain.management import ManagementError
from projects.infrastructure._projection_binding import _ProjectionBinding
from projects.infrastructure.owner_event_records import EntityChangedEvent
from projects.infrastructure.panel_journal import (
    INVITATION_REVISION,
    InvitationEvidence,
    InvitationPending,
    InvitationReceipt,
    InviterReceipt,
)
from service_runtime.platform_db_mechanics import (
    _PrivateDatabaseBinding,
    _SessionBinding,
)


class InvitationProjection(Protocol):
    async def resolve(
        self, *, issuer: str, subject: str
    ) -> CurrentRauthyPlatformMembership | None: ...


class ProjectionInvitationAuthority(_ProjectionBinding[InvitationProjection]):
    async def fresh_expiry(
        self,
        identity: InvitationIdentity,
        actor: InvitationActor,
    ) -> datetime | None:
        fresh = await self._projection.resolve(issuer=identity.issuer, subject=identity.subject)
        return None if fresh is None or fresh.user_id != actor.uuid else fresh.expires_at


class SqlInvitationUnitOfWork(_PrivateDatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[InvitationTransaction]:
        async with self._database.transaction() as tx:
            yield SqlInvitationTransaction(tx)


class SqlInvitationTransaction(_SessionBinding[AsyncSession]):
    async def granted(self, user_uuid: UUID) -> bool:
        row = await self._session.scalar(
            select(OwnerAuditRow)
            .where(
                OwnerAuditRow.action == "panel.inviter.set",
                OwnerAuditRow.object_id == str(user_uuid),
            )
            .order_by(OwnerAuditRow.created_at.desc(), OwnerAuditRow.id.desc())
            .limit(1)
        )
        if row is None:
            return False
        try:
            evidence = InvitationEvidence.load(row)
        except ValueError:
            return False
        receipt = evidence.outcome
        return (
            evidence.enabled is True
            and isinstance(receipt, InviterReceipt)
            and receipt.enabled
            and receipt.id == user_uuid
        )

    async def capabilities(
        self,
        identity: InvitationIdentity,
        actor: InvitationActor,
    ) -> InvitationCapabilities:
        allowed = actor.operator or await self.granted(actor.uuid)
        inviter_ids: list[UUID] = []
        if actor.operator:
            users = await self._session.scalars(
                select(RauthyUserLinkRow)
                .where(
                    RauthyUserLinkRow.issuer == identity.issuer,
                )
                .limit(101)
            )
            inviter_ids.extend([user.user_id for user in users if await self.granted(user.user_id)])
        return InvitationCapabilities(allowed, actor.operator, tuple(inviter_ids), None)

    async def lock(self, command: InvitationCommand) -> None:
        names = {"invitation:" + str(command.actor.uuid), str(command.operation_uuid)}
        if isinstance(command.change, SetInviter):
            names.add("invitation:" + str(command.change.user_uuid))
        else:
            names.add("invitation-email:" + command.change.email.value)
        for lock_name in sorted(names):
            await self._session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
                {"key": lock_name},
            )

    async def require_actor(self, command: InvitationCommand) -> None:
        link = await self._session.get(RauthyUserLinkRow, command.actor.uuid, with_for_update=True)
        if link is None or not link.active or link.issuer != command.identity.issuer:
            raise ManagementError(403, "INVITER_REQUIRED")
        operator = link.briareus_role == "operator"
        if isinstance(command.change, SetInviter):
            if not operator:
                raise ManagementError(403, "PLATFORM_OPERATOR_REQUIRED")
        elif not (operator or await self.granted(command.actor.uuid)):
            raise ManagementError(403, "INVITER_REQUIRED")

    async def previous(self, command: InvitationCommand) -> InvitationResult | None:
        old = await self._session.get(OwnerAuditRow, command.operation_uuid)
        if old is None:
            return None
        try:
            evidence = InvitationEvidence.load(old)
        except ValueError:
            raise ManagementError(409, "INVITATION_OUTCOME_UNCONFIRMED") from None
        if old.actor_user_id != command.actor.uuid or evidence.fingerprint != command.fingerprint:
            raise ManagementError(409, "OPERATION_CONFLICT")
        receipt = evidence.outcome
        if isinstance(command.change, SetInviter) and isinstance(receipt, InviterReceipt):
            return InviterOutcome(receipt.id, receipt.enabled)
        if isinstance(command.change, IssueInvitation) and isinstance(receipt, InvitationReceipt):
            return InvitationOutcome(receipt.id)
        raise ManagementError(409, "INVITATION_OUTCOME_UNCONFIRMED")

    async def set_inviter(self, command: InvitationCommand, change: SetInviter) -> InviterOutcome:
        target = await self._session.get(RauthyUserLinkRow, change.user_uuid, with_for_update=True)
        if target is None or not target.active or target.issuer != command.identity.issuer:
            raise ManagementError(404, "USER_NOT_FOUND")
        outcome = InviterOutcome(target.user_id, change.enabled)
        self._session.add(
            OwnerAuditRow(
                id=command.operation_uuid,
                operation_uuid=command.operation_uuid,
                actor_user_id=command.actor.uuid,
                project_id=None,
                action="panel.inviter.set",
                object_id=str(outcome.id),
                owner_revision=INVITATION_REVISION,
                details=InvitationEvidence(
                    fingerprint=command.fingerprint,
                    enabled=change.enabled,
                    outcome=InviterReceipt(
                        id=outcome.id, enabled=outcome.enabled, state="committed"
                    ),
                ),
            )
        )
        self._event(command, "panel.inviter.set", outcome.id)
        return outcome

    async def record_intent(self, command: InvitationCommand, change: IssueInvitation) -> None:
        recent = await self._session.scalar(
            select(OwnerAuditRow)
            .where(
                OwnerAuditRow.action == "panel.invitation.issue",
                OwnerAuditRow.details["email"].astext == change.email.value,
            )
            .limit(1)
        )
        if recent is not None:
            raise ManagementError(409, "INVITATION_ALREADY_REQUESTED")
        self._session.add(
            OwnerAuditRow(
                id=command.operation_uuid,
                operation_uuid=command.operation_uuid,
                actor_user_id=command.actor.uuid,
                project_id=None,
                action="panel.invitation.issue",
                object_id=str(command.operation_uuid),
                owner_revision=INVITATION_REVISION,
                details=InvitationEvidence(
                    fingerprint=command.fingerprint,
                    email=change.email.value,
                    outcome=InvitationPending(state="issuing"),
                ),
            )
        )

    async def finish(self, command: InvitationCommand, user: ProviderUser) -> InvitationOutcome:
        row = await self._session.get(OwnerAuditRow, command.operation_uuid, with_for_update=True)
        if row is None:
            raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED")
        try:
            evidence = InvitationEvidence.load(row)
        except ValueError:
            raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED") from None
        if row.actor_user_id != command.actor.uuid or evidence.fingerprint != command.fingerprint:
            raise ManagementError(503, "INVITATION_OUTCOME_UNCONFIRMED")
        outcome = InvitationOutcome(user.subject)
        row.details = InvitationEvidence(
            fingerprint=evidence.fingerprint,
            email=evidence.email,
            enabled=evidence.enabled,
            outcome=InvitationReceipt(
                id=outcome.id, state="provider_created", delivery="unconfirmed"
            ),
        )
        self._event(command, "panel.invitation.issue", outcome.id)
        return outcome

    def _event(self, command: InvitationCommand, event_name: str, identifier: UUID | str) -> None:
        self._session.add(
            OwnerOutboxRow(
                operation_uuid=command.operation_uuid,
                event_name=event_name,
                owner_revision=INVITATION_REVISION,
                event_payload=EntityChangedEvent(id=identifier),
            )
        )
