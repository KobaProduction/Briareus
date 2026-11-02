"""Protected legacy setup-code delivery after its owned transaction commits."""

from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Protocol

from common.platform_errors import Conflict
from identity.application.invitations import InvitationSecrets


class SetupOperator(Protocol):
    def require(self) -> None: ...


class SetupTransaction(Protocol):
    async def lock_claimed(self) -> bool: ...

    async def active_superusers(self) -> bool: ...

    async def revoke_pending(self, now: datetime) -> None: ...

    async def issue(self, digest: str, expires_at: datetime) -> None: ...


class SetupTransactions(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[SetupTransaction]: ...


@dataclass(frozen=True)
class LegacySetupCode:
    value: str = field(repr=False)


@dataclass(frozen=True)
class IssueLegacyFirstAdminSetup:
    operator: SetupOperator
    transactions: SetupTransactions
    secrets: InvitationSecrets
    now: Callable[[], datetime]

    async def execute(self) -> LegacySetupCode:
        self.operator.require()
        async with self.transactions() as tx:
            if await tx.lock_claimed():
                raise Conflict("initial superuser is already established")
            if await tx.active_superusers():
                raise Conflict("an active superuser already exists")
            now = self.now()
            await tx.revoke_pending(now)
            raw = self.secrets.random_token()
            await tx.issue(self.secrets.token_digest(raw), now + timedelta(hours=24))
        return LegacySetupCode(raw)
