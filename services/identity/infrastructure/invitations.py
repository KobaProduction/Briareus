"""Owner SQL and configured URL adapters for legacy invitations."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import UserId
from identity._domain import UserRole
from identity._persistence import InvitationRow
from identity.application.invitations import (
    InvitationActor,
    InvitationTransaction,
    IssuedInvitationReceipt,
    PendingInvitation,
)
from identity.domain.invitations import RevocableInvitation
from identity.infrastructure.registration import RegistrationHost


class InvitationHost(RegistrationHost, Protocol):
    def _link(self, kind: str, raw_token: str) -> str: ...


@dataclass(frozen=True)
class LegacyInvitationLinks:
    host: InvitationHost

    def link(self, kind: str, raw: str) -> str:
        return self.host._link(kind, raw)


@dataclass
class SqlInvitationTransaction:
    host: InvitationHost
    tx: AsyncSession
    selected: InvitationRow | None = None

    async def user(self, user_id: UUID) -> InvitationActor | None:
        row = await self.host.repository.get_user(self.tx, UserId(user_id))
        if row is None:
            return None
        return InvitationActor(row.enabled, UserRole(row.role), row.credential_version)

    def issue(self, invitation: PendingInvitation) -> IssuedInvitationReceipt:
        row = InvitationRow(
            id=uuid4(),
            kind=invitation.kind,
            token_digest=invitation.token_digest,
            created_by_user_id=invitation.issuer_id,
            target_user_id=invitation.target_id,
            expires_at=invitation.expires_at,
        )
        self.tx.add(row)
        return IssuedInvitationReceipt(row.id)

    async def lock_invitation(self, invitation_id: UUID) -> RevocableInvitation | None:
        self.selected = await self.host.repository.get_invitation(self.tx, invitation_id, lock=True)
        if self.selected is None:
            return None
        return RevocableInvitation(
            self.selected.id,
            self.selected.created_by_user_id,
            self.selected.used_at,
            self.selected.revoked_at,
        )

    def revoke(self, now: datetime) -> None:
        if self.selected is None:
            raise RuntimeError("invitation revocation requires a locked invitation")
        self.selected.revoked_at = now

    def record(self, actor_id: UUID, target_id: UUID, event: str, revision: int) -> None:
        self.host._record_local_security_event(
            self.tx,
            actor_id=UserId(actor_id),
            target_id=target_id,
            event=event,
            credential_version=revision,
        )


@dataclass(frozen=True)
class SqlInvitationTransactions:
    host: InvitationHost
    existing: AsyncSession | None

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[InvitationTransaction]:
        async with self.host._transaction(self.existing) as tx:
            yield SqlInvitationTransaction(self.host, tx)
