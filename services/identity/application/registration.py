"""Legacy registration orchestration with protected invitation consistency."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from common.platform_errors import Conflict, InvalidInput, InvalidInvitation
from identity._domain import User, UserRole, canonical_username
from identity.domain.registration import (
    RegistrationDenied,
    RegistrationInvitationState,
    require_password_length,
)


class RegistrationCredentials(Protocol):
    def token_digest(self, invitation: str) -> str: ...

    async def password_digest(self, password: str) -> str: ...


class RegistrationTransaction(Protocol):
    async def probe(self, digest: str) -> RegistrationInvitationState | None: ...

    async def lock_bootstrap(self) -> bool: ...

    async def lock_invitation(self, digest: str) -> RegistrationInvitationState | None: ...

    async def issuer_active(self, issuer_id: UUID) -> bool: ...

    async def username_taken(self, username: str) -> bool: ...

    async def complete(self, username: str, password_digest: str, role: UserRole) -> User: ...


class RegistrationTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[RegistrationTransaction]: ...


@dataclass(frozen=True)
class RegisterLegacyUser:
    transactions: RegistrationTransactions
    credentials: RegistrationCredentials
    now: Callable[[], datetime]

    async def execute(self, *, invitation: str, username: str, password: str) -> User:
        try:
            require_password_length(password)
            normalized = canonical_username(username)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
        digest = self.credentials.token_digest(invitation)
        async with self.transactions() as tx:
            self._require_invitation(await tx.probe(digest), preflight=True)
        password_digest = await self.credentials.password_digest(password)
        async with self.transactions() as tx:
            claimed = await tx.lock_bootstrap()
            state = self._require_invitation(await tx.lock_invitation(digest))
            if state.issuer_id is not None and not await tx.issuer_active(state.issuer_id):
                raise InvalidInvitation("invitation issuer is no longer active")
            if await tx.username_taken(normalized):
                raise Conflict("username is unavailable")
            try:
                role = state.registration_role(first_superuser_claimed=claimed)
            except RegistrationDenied as exc:
                raise InvalidInvitation(str(exc)) from exc
            return await tx.complete(normalized, password_digest, role)

    def _require_invitation(
        self, state: RegistrationInvitationState | None, *, preflight: bool = False
    ) -> RegistrationInvitationState:
        if state is None:
            raise InvalidInvitation("invitation is invalid or unavailable")
        try:
            state.require_available(self.now(), preflight=preflight)
        except RegistrationDenied as exc:
            raise InvalidInvitation(str(exc)) from exc
        return state
