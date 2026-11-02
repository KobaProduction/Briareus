"""Owner-local first-user REST service behind the internal Admin API.

No service-identity impersonation: direct HTTP is the deliberately selected
Briareus Development transport. Identity itself verifies User/JWT/JTI using
its own database. The per-process Ed25519 signer expires all sessions after
a restart; no key is exported and no uninvited first administrator is created.
"""

from __future__ import annotations

from uuid import UUID

from common.owner_bff_models import VerifiedAdminCaller
from common.platform_db import PlatformDatabase
from identity._domain import User
from identity._repository import IdentityRepository
from identity._service import IdentityService
from identity.application.first_user import (
    FirstUserBearer,
    LoginFirstUserSession,
    LogoutFirstUser,
    ReadCurrentFirstUser,
)
from identity.application.first_user import (
    OriginalLoginUnavailable as OriginalLoginUnavailable,
)
from identity.application.first_user import (
    SignedIdentityDenied as SignedIdentityDenied,
)
from identity.infrastructure.first_user import (
    _AUDIENCE as _AUDIENCE,
)
from identity.infrastructure.first_user import (
    _ISSUER as _ISSUER,
)
from identity.infrastructure.first_user import (
    _PURPOSE as _PURPOSE,
)
from identity.infrastructure.first_user import (
    _TYPE as _TYPE,
)
from identity.infrastructure.first_user import (
    EphemeralFirstUserTokens,
    SqlFirstUserLedger,
    SqlFirstUserTransactions,
    generate_first_user_authority,
)


class DirectFirstUserIdentity:
    def __init__(self, *, identity: IdentityService, database: PlatformDatabase) -> None:
        if identity.database is not database or database.engine.url.database != "briareus_identity":
            raise ValueError("direct first-user sessions require the Identity owner database")
        self.identity = identity
        self.db = database
        self.repo = IdentityRepository()
        # Keep one ephemeral signing key and independent pepper per source
        # instance. Restart still invalidates every retained legacy session.
        authority = generate_first_user_authority()
        self._key = authority.key
        self._kid = authority.kid
        self._pepper = authority.pepper

    async def register(self, invitation: str, username: str, password: str) -> User:
        return await self.identity.register(
            invitation=invitation, username=username, password=password
        )

    async def _reserve_login(self, operation: UUID, username: str, source: str) -> UUID:
        return await SqlFirstUserLedger(self.db, self._pepper).reserve(operation, username, source)

    async def _complete_login(self, receipt: UUID) -> None:
        await SqlFirstUserLedger(self.db, self._pepper).complete(receipt)

    async def login(
        self, *, username: str, password: str, source: str, operation: UUID
    ) -> FirstUserBearer:
        return await LoginFirstUserSession(
            self.identity, self, self._transactions(), self._tokens(), self._pepper
        ).execute(username=username, password=password, source=source, operation=operation)

    async def current(self, bearer: str) -> VerifiedAdminCaller:
        return await ReadCurrentFirstUser(self._transactions(), self._tokens()).execute(bearer)

    async def logout(self, bearer: str) -> None:
        await LogoutFirstUser(self, self._transactions(), self._tokens()).execute(bearer)

    def _tokens(self) -> EphemeralFirstUserTokens:
        return EphemeralFirstUserTokens(self._key, self._kid)

    def _transactions(self) -> SqlFirstUserTransactions:
        return SqlFirstUserTransactions(self.db, self.repo)
