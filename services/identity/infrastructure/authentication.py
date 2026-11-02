"""Owner SQL snapshots and current revision checks for legacy credentials."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_ids import UserId
from identity._domain import User
from identity._repository import IdentityRepository, to_user
from identity.application.authentication import AuthenticationTransaction, CredentialSnapshot


@dataclass(frozen=True)
class SqlAuthenticationTransaction:
    tx: AsyncSession
    repository: IdentityRepository

    async def candidate(self, username: str) -> CredentialSnapshot | None:
        row = await self.repository.username_row(self.tx, username)
        if row is None or not row.enabled:
            return None
        return CredentialSnapshot(row.id, row.credential_version, row.password_digest)

    async def confirm(self, snapshot: CredentialSnapshot) -> User | None:
        current = await self.repository.get_user(self.tx, UserId(snapshot.subject_id), lock=True)
        if (
            current is None
            or not current.enabled
            or current.credential_version != snapshot.credential_version
            or current.password_digest != snapshot.digest
        ):
            return None
        return to_user(current)


@dataclass(frozen=True)
class SqlAuthenticationTransactions:
    database: PlatformDatabase
    repository: IdentityRepository

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[AuthenticationTransaction]:
        async with self.database.transaction() as tx:
            yield SqlAuthenticationTransaction(tx, self.repository)
