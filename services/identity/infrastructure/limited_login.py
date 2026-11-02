"""Legacy throttle SQL locking and credential primitives."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_errors import AccessDenied
from identity._domain import User
from identity._persistence import LoginAttemptRow, UserRow
from identity._repository import IdentityRepository, to_user
from identity.application.limited_login import LoginCandidate, LoginTransaction
from identity.domain.login_attempts import LoginAttemptState


@dataclass
class SqlLoginTransaction:
    tx: AsyncSession
    repository: IdentityRepository
    dummy_password_digest: str
    selected: UserRow | None = None
    rows: dict[str, LoginAttemptRow] = field(default_factory=dict)

    async def lock_attempts(self, keys: tuple[str, ...]) -> tuple[LoginAttemptState, ...]:
        states: list[LoginAttemptState] = []
        for key in keys:
            await self.tx.execute(
                insert(LoginAttemptRow)
                .values(bucket_key=key, failures=0)
                .on_conflict_do_nothing(index_elements=["bucket_key"])
            )
            row = await self.tx.scalar(
                select(LoginAttemptRow).where(LoginAttemptRow.bucket_key == key).with_for_update()
            )
            if row is None:
                raise AccessDenied("login attempts cannot be verified")
            self.rows[key] = row
            states.append(
                LoginAttemptState(key, row.failures, row.last_failed_at, row.blocked_until)
            )
        return tuple(states)

    async def candidate(self, username: str | None) -> LoginCandidate:
        row = (
            await self.repository.username_row(self.tx, username) if username is not None else None
        )
        stored = (
            row.password_digest if row is not None and row.enabled else self.dummy_password_digest
        )
        self.selected = row
        return LoginCandidate(row is not None and row.enabled, stored)

    def authenticated_user(self) -> User:
        if self.selected is None or not self.selected.enabled:
            raise AccessDenied("login account cannot be verified")
        return to_user(self.selected)

    def save_attempts(self, attempts: tuple[LoginAttemptState, ...]) -> None:
        for attempt in attempts:
            row = self.rows[attempt.key]
            row.failures = attempt.failures
            row.last_failed_at = attempt.last_failed_at
            row.blocked_until = attempt.blocked_until


@dataclass(frozen=True)
class SqlLoginTransactions:
    database: PlatformDatabase
    repository: IdentityRepository
    dummy_password_digest: str

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[LoginTransaction]:
        async with self.database.transaction() as tx:
            yield SqlLoginTransaction(tx, self.repository, self.dummy_password_digest)
