"""Legacy password verification with a current credential revision fence."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from typing import Protocol
from uuid import UUID

from identity._domain import User, canonical_username


@dataclass(frozen=True)
class CredentialSnapshot:
    subject_id: UUID
    credential_version: int
    digest: str = field(repr=False)


class PasswordVerification(Protocol):
    async def verify(self, password: str, digest: str) -> bool: ...


class AuthenticationTransaction(Protocol):
    async def candidate(self, username: str) -> CredentialSnapshot | None: ...

    async def confirm(self, snapshot: CredentialSnapshot) -> User | None: ...


class AuthenticationTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AuthenticationTransaction]: ...


@dataclass(frozen=True)
class AuthenticateLegacyUser:
    transactions: AuthenticationTransactions
    passwords: PasswordVerification

    async def execute(self, username: str, password: str) -> User | None:
        try:
            normalized = canonical_username(username)
        except ValueError:
            return None
        async with self.transactions() as tx:
            snapshot = await tx.candidate(normalized)
        if snapshot is None or not await self.passwords.verify(password, snapshot.digest):
            return None
        async with self.transactions() as tx:
            return await tx.confirm(snapshot)
