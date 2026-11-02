"""Legacy credential verification under transactional source and identity throttles."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from common.platform_errors import AuthenticationRateLimited
from identity._domain import User, canonical_username
from identity.domain.login_attempts import LoginAttemptState, LoginBlocked


@dataclass(frozen=True)
class LoginThrottleKeys:
    identity: str
    source: str

    @property
    def ordered(self) -> tuple[str, ...]:
        return tuple(sorted({self.identity, self.source}))


@dataclass(frozen=True)
class LoginCandidate:
    eligible: bool
    password_digest: str


class LoginCredentials(Protocol):
    def keys(self, username: str, source: str, pepper: bytes) -> LoginThrottleKeys: ...

    async def verify(self, password: str, digest: str) -> bool: ...


class LoginTransaction(Protocol):
    async def lock_attempts(self, keys: tuple[str, ...]) -> tuple[LoginAttemptState, ...]: ...

    async def candidate(self, username: str | None) -> LoginCandidate: ...

    def save_attempts(self, attempts: tuple[LoginAttemptState, ...]) -> None: ...

    def authenticated_user(self) -> User: ...


class LoginTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[LoginTransaction]: ...


@dataclass(frozen=True)
class AuthenticateLimitedLegacyUser:
    transactions: LoginTransactions
    credentials: LoginCredentials
    now: Callable[[], datetime]

    async def execute(
        self, username: str, password: str, *, source: str, pepper: bytes
    ) -> User | None:
        keys = self.credentials.keys(username, source, pepper)
        async with self.transactions() as tx:
            attempts = await tx.lock_attempts(keys.ordered)
            now = self.now()
            self._prepare(attempts, now)
            candidate = await tx.candidate(self._canonical(username))
            valid = await self.credentials.verify(password, candidate.password_digest)
            if not valid or not candidate.eligible:
                self._failed(attempts, keys, now)
                tx.save_attempts(attempts)
                return None
            for attempt in attempts:
                if attempt.key == keys.identity:
                    attempt.succeed()
            tx.save_attempts(attempts)
            return tx.authenticated_user()

    @staticmethod
    def _canonical(username: str) -> str | None:
        try:
            return canonical_username(username)
        except ValueError:
            return None

    @staticmethod
    def _prepare(attempts: tuple[LoginAttemptState, ...], now: datetime) -> None:
        try:
            for attempt in attempts:
                attempt.prepare(now)
        except LoginBlocked as exc:
            raise AuthenticationRateLimited(str(exc)) from exc

    @staticmethod
    def _failed(
        attempts: tuple[LoginAttemptState, ...], keys: LoginThrottleKeys, now: datetime
    ) -> None:
        for attempt in attempts:
            attempt.fail(now, limit=40 if attempt.key == keys.source else 5)
