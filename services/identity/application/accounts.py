"""Legacy account changes against owner-local transaction and credential ports."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from common.platform_errors import (
    AccessDenied,
    InvalidInput,
    InvalidInvitation,
    LastSuperuser,
    ResourceMissing,
)
from identity._domain import User
from identity.domain.accounts import AccountSnapshot, LastAdministrator, PasswordResetState
from identity.domain.registration import require_password_length


@dataclass(frozen=True)
class AccountChange:
    account: AccountSnapshot
    actor_id: UUID | None
    event: str
    redeem_reset: bool = False
    revoke_invitations: bool = False


class AccountCredentials(Protocol):
    def token_digest(self, token: str) -> str: ...

    async def password_digest(self, password: str) -> str: ...

    async def verify(self, password: str, digest: str) -> bool: ...


class AccountTransaction(Protocol):
    async def lock_bootstrap(self) -> None: ...

    async def user(self, user_id: UUID, *, lock: bool = False) -> AccountSnapshot | None: ...

    async def active_superusers(self) -> int: ...

    async def lock_reset(self, digest: str) -> PasswordResetState | None: ...

    async def save(self, change: AccountChange) -> User: ...


class AccountTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[AccountTransaction]: ...


@dataclass(frozen=True)
class LegacyAccountLifecycle:
    transactions: AccountTransactions
    credentials: AccountCredentials
    now: Callable[[], datetime]

    async def change_password(self, actor: UUID, current_password: str, new_password: str) -> None:
        self._password_length(new_password)
        digest = await self.credentials.password_digest(new_password)
        async with self.transactions() as tx:
            user = await tx.user(actor, lock=True)
            if user is None or not user.enabled:
                raise AccessDenied("current user is not active")
            if not await self.credentials.verify(current_password, user.password_digest):
                raise AccessDenied("current password is invalid")
            await tx.save(
                AccountChange(user.with_password(digest), actor, "identity.password_changed")
            )

    async def reset_password(self, token: str, password: str) -> User:
        self._password_length(password)
        digest = await self.credentials.password_digest(password)
        async with self.transactions() as tx:
            reset = await tx.lock_reset(self.credentials.token_digest(token))
            if reset is None or not reset.available(self.now()) or reset.target_id is None:
                raise InvalidInvitation("password reset token is invalid or expired")
            user = await tx.user(reset.target_id, lock=True)
            if user is None or not user.enabled:
                raise InvalidInvitation("password reset user is not active")
            return await tx.save(
                AccountChange(
                    user.with_password(digest),
                    reset.issuer_id,
                    "identity.password_reset",
                    redeem_reset=True,
                )
            )

    async def set_superuser(self, admin: UUID, target: UUID, enabled: bool) -> User:
        async with self.transactions() as tx:
            await tx.lock_bootstrap()
            await self._require_admin(tx, admin)
            user = self._require_user(await tx.user(target, lock=True))
            count = await tx.active_superusers() if user.role == "superuser" and not enabled else 0
            try:
                changed = user.with_superuser(enabled, count)
            except LastAdministrator as exc:
                raise LastSuperuser(str(exc)) from exc
            return await tx.save(AccountChange(changed, admin, "identity.role_changed"))

    async def set_suspended(self, admin: UUID, target: UUID, suspend: bool) -> User:
        async with self.transactions() as tx:
            await tx.lock_bootstrap()
            await self._require_admin(tx, admin)
            user = self._require_user(await tx.user(target, lock=True))
            count = (
                await tx.active_superusers()
                if suspend and user.enabled and user.role == "superuser"
                else 0
            )
            try:
                changed = user.with_suspension(suspend, count)
            except LastAdministrator as exc:
                raise LastSuperuser(str(exc)) from exc
            return await tx.save(
                AccountChange(
                    changed,
                    admin,
                    "identity.suspended" if suspend else "identity.restored",
                    revoke_invitations=suspend,
                )
            )

    @staticmethod
    async def _require_admin(tx: AccountTransaction, admin: UUID) -> None:
        actor = await tx.user(admin)
        if actor is None or not actor.enabled or actor.role != "superuser":
            raise AccessDenied("active superuser required")

    @staticmethod
    def _require_user(user: AccountSnapshot | None) -> AccountSnapshot:
        if user is None:
            raise ResourceMissing("user not found")
        return user

    @staticmethod
    def _password_length(password: str) -> None:
        try:
            require_password_length(password)
        except ValueError as exc:
            raise InvalidInput(str(exc)) from exc
