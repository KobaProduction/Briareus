"""Owner-local SQL account transitions and legacy credential primitives."""

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_ids import UserId
from identity._domain import User, UserRole
from identity._persistence import InvitationRow, UserRow
from identity._repository import to_user
from identity.application.accounts import AccountChange, AccountTransaction
from identity.domain.accounts import AccountSnapshot, PasswordResetState
from identity.infrastructure.registration import RegistrationHost


@dataclass
class SqlAccountTransaction:
    host: RegistrationHost
    tx: AsyncSession
    now: Callable[[], datetime]
    users: dict[UUID, UserRow] = field(default_factory=dict)
    reset: InvitationRow | None = None

    async def lock_bootstrap(self) -> None:
        await self.host.repository.lock_bootstrap(self.tx)

    async def user(self, user_id: UUID, *, lock: bool = False) -> AccountSnapshot | None:
        row = await self.host.repository.get_user(self.tx, UserId(user_id), lock=lock)
        if row is None:
            return None
        self.users[user_id] = row
        return AccountSnapshot(
            row.id,
            row.username,
            UserRole(row.role),
            row.enabled,
            row.credential_version,
            row.password_digest,
        )

    async def active_superusers(self) -> int:
        return len(await self.host.repository.list_active_superusers(self.tx))

    async def lock_reset(self, digest: str) -> PasswordResetState | None:
        self.reset = await self.host.repository.lock_invitation(self.tx, digest)
        if self.reset is None:
            return None
        return PasswordResetState(
            self.reset.kind,
            self.reset.used_at,
            self.reset.revoked_at,
            self.reset.expires_at,
            self.reset.target_user_id,
            self.reset.created_by_user_id,
        )

    async def save(self, change: AccountChange) -> User:
        state = change.account
        row = self.users[state.user_id]
        row.password_digest = state.password_digest
        row.role = state.role.value
        row.enabled = state.enabled
        row.credential_version = state.credential_version
        row.updated_at = self.now()
        if change.redeem_reset:
            if self.reset is None:
                raise RuntimeError("password reset requires a locked invitation")
            self.reset.used_at = self.now()
        if change.revoke_invitations:
            await self.host.repository.revoke_outstanding_invitations(
                self.tx, UserId(row.id), self.now()
            )
        self.host._record_local_security_event(
            self.tx,
            actor_id=UserId(change.actor_id) if change.actor_id is not None else None,
            target_id=row.id,
            event=change.event,
            credential_version=row.credential_version,
        )
        return to_user(row)


@dataclass(frozen=True)
class SqlAccountTransactions:
    host: RegistrationHost
    existing: AsyncSession | None
    now: Callable[[], datetime]

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AccountTransaction]:
        async with self.host._transaction(self.existing) as tx:
            yield SqlAccountTransaction(self.host, tx, self.now)
