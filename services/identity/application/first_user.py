"""Retained first-user session scenarios over owner-local authority ports."""

from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import NamedTuple, Protocol
from uuid import UUID

from common.owner_bff_models import VerifiedAdminCaller
from identity._domain import User
from identity.domain.current_user import CurrentUserSnapshot


class OriginalLoginUnavailable(Exception):
    """An original operation may already have issued a bearer; never replay."""


class SignedIdentityDenied(Exception):
    """Invalid/disabled/expired/revoked signed user, distinct from unavailable SQL."""


class FirstUserBearer(NamedTuple):
    access_token: str
    expires_at: datetime


@dataclass(frozen=True)
class FirstUserToken:
    subject_id: UUID
    credential_version: int
    jti: UUID
    expires_at: datetime


class FirstUserCredentials(Protocol):
    async def authenticate_limited(
        self, username: str, password: str, *, source: str, pepper: bytes
    ) -> User | None: ...


class FirstUserTokens(Protocol):
    def issue(self, user: User) -> FirstUserBearer: ...

    def require(self, bearer: str) -> FirstUserToken: ...


class FirstUserOriginalLedger(Protocol):
    async def _reserve_login(self, operation: UUID, username: str, source: str) -> UUID: ...

    async def _complete_login(self, receipt: UUID) -> None: ...


class FirstUserTransaction(Protocol):
    async def user(self, subject_id: UUID, *, lock: bool = False) -> CurrentUserSnapshot | None: ...

    async def revoked(self, jti: UUID) -> bool: ...

    async def revoke(self, token: FirstUserToken) -> None: ...


class FirstUserTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[FirstUserTransaction]: ...


class CurrentFirstUser(Protocol):
    async def current(self, bearer: str) -> VerifiedAdminCaller: ...


@dataclass(frozen=True)
class LoginFirstUserSession:
    credentials: FirstUserCredentials
    ledger: FirstUserOriginalLedger
    transactions: FirstUserTransactions
    tokens: FirstUserTokens
    pepper: bytes

    async def execute(
        self, *, username: str, password: str, source: str, operation: UUID
    ) -> FirstUserBearer:
        user = await self.credentials.authenticate_limited(
            username, password, source=source, pepper=self.pepper
        )
        if user is None or not user.enabled:
            raise SignedIdentityDenied
        receipt = await self.ledger._reserve_login(operation, username, source)
        async with self.transactions() as tx:
            current = await tx.user(user.id, lock=True)
            if current is None or not current.current(user.credential_version):
                raise SignedIdentityDenied
            issued = self.tokens.issue(user)
        # Commit of the locked current-user check precedes completion. A lost
        # completion remains unknown and must not mint another original bearer.
        await self.ledger._complete_login(receipt)
        return issued


@dataclass(frozen=True)
class ReadCurrentFirstUser:
    transactions: FirstUserTransactions
    tokens: FirstUserTokens

    async def execute(self, bearer: str) -> VerifiedAdminCaller:
        try:
            token = self.tokens.require(bearer)
        except Exception:
            raise SignedIdentityDenied from None
        async with self.transactions() as tx:
            current = await tx.user(token.subject_id)
            if current is None or not current.current(token.credential_version):
                raise SignedIdentityDenied
            if await tx.revoked(token.jti):
                raise SignedIdentityDenied
        return VerifiedAdminCaller(
            user_id=token.subject_id,
            credential_version=token.credential_version,
            source="verified-admin-bearer",
        )


@dataclass(frozen=True)
class LogoutFirstUser:
    current: CurrentFirstUser
    transactions: FirstUserTransactions
    tokens: FirstUserTokens

    async def execute(self, bearer: str) -> None:
        await self.current.current(bearer)
        token = self.tokens.require(bearer)
        async with self.transactions() as tx:
            await tx.revoke(token)
