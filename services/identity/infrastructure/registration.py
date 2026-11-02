"""SQL and password implementations for protected legacy registration."""

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID, uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import UserId
from identity._domain import User, UserRole
from identity._persistence import BootstrapRow, InvitationRow, UserRow
from identity._repository import IdentityRepository, to_user
from identity.application.registration import RegistrationTransaction
from identity.domain.registration import RegistrationInvitationState


class RegistrationHost(Protocol):
    repository: IdentityRepository

    def _transaction(
        self, existing: AsyncSession | None
    ) -> AbstractAsyncContextManager[AsyncSession]: ...

    def _record_local_security_event(
        self,
        tx: AsyncSession,
        *,
        actor_id: UserId | None,
        target_id: UUID,
        event: str,
        credential_version: int,
    ) -> None: ...


def invitation_state(row: InvitationRow | None) -> RegistrationInvitationState | None:
    if row is None:
        return None
    return RegistrationInvitationState(
        row.kind, row.expires_at, row.used_at, row.revoked_at, row.created_by_user_id
    )


@dataclass
class SqlRegistrationTransaction:
    host: RegistrationHost
    tx: AsyncSession
    now: Callable[[], datetime]
    bootstrap: BootstrapRow | None = None
    invitation: InvitationRow | None = None

    async def probe(self, digest: str) -> RegistrationInvitationState | None:
        return invitation_state(await self.host.repository.peek_invitation(self.tx, digest))

    async def lock_bootstrap(self) -> bool:
        self.bootstrap = await self.host.repository.lock_bootstrap(self.tx)
        return self.bootstrap.first_superuser_claimed

    async def lock_invitation(self, digest: str) -> RegistrationInvitationState | None:
        self.invitation = await self.host.repository.lock_invitation(self.tx, digest)
        return invitation_state(self.invitation)

    async def issuer_active(self, issuer_id: UUID) -> bool:
        issuer = await self.host.repository.get_user(self.tx, UserId(issuer_id))
        return issuer is not None and issuer.enabled

    async def username_taken(self, username: str) -> bool:
        return await self.host.repository.username_taken(self.tx, username)

    async def complete(self, username: str, password_digest: str, role: UserRole) -> User:
        if self.invitation is None or self.bootstrap is None:
            raise RuntimeError("registration requires locked bootstrap and invitation")
        user = UserRow(
            id=uuid4(),
            username=username,
            password_digest=password_digest,
            role=role.value,
            enabled=True,
            credential_version=1,
        )
        self.tx.add(user)
        self.invitation.used_at = self.now()
        self.bootstrap.first_superuser_claimed = True
        await self.tx.flush()
        self.host._record_local_security_event(
            self.tx,
            actor_id=(
                UserId(self.invitation.created_by_user_id)
                if self.invitation.created_by_user_id
                else None
            ),
            target_id=user.id,
            event="identity.registered",
            credential_version=user.credential_version,
        )
        return to_user(user)


@dataclass(frozen=True)
class SqlRegistrationTransactions:
    host: RegistrationHost
    existing: AsyncSession | None
    now: Callable[[], datetime]

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[RegistrationTransaction]:
        async with self.host._transaction(self.existing) as tx:
            yield SqlRegistrationTransaction(self.host, tx, self.now)
