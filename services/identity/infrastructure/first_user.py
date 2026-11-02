"""Retained ephemeral bearer, original-operation ledger and owner SQL adapters."""

import hashlib
import hmac
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from common.platform_ids import UserId
from common.private_user_token import (
    jti_digest,
    pinned_ed25519_kid,
    require_pinned_current_user_token,
)
from identity._domain import User
from identity._owner_ledger import OwnerCommandRow
from identity._persistence import AdminTokenRevocationRow
from identity._repository import IdentityRepository
from identity.application.first_user import (
    FirstUserBearer,
    FirstUserToken,
    FirstUserTransaction,
    OriginalLoginUnavailable,
)
from identity.domain.current_user import CurrentUserSnapshot

_ISSUER = "briareus:identity"
_AUDIENCE = "briareus:panel"
_PURPOSE = "briareus-panel-user-v1"
_TYPE = "briareus-user-bearer+jwt"


@dataclass(frozen=True)
class FirstUserAuthority:
    key: Ed25519PrivateKey = field(repr=False)
    kid: str
    pepper: bytes = field(repr=False)


def generate_first_user_authority() -> FirstUserAuthority:
    key = Ed25519PrivateKey.generate()
    kid = pinned_ed25519_kid(key.public_key())
    return FirstUserAuthority(key, kid, secrets.token_bytes(32))


@dataclass(frozen=True)
class EphemeralFirstUserTokens:
    key: Ed25519PrivateKey = field(repr=False)
    kid: str

    def issue(self, user: User) -> FirstUserBearer:
        now = datetime.now(UTC)
        expires = now + timedelta(minutes=15)
        encoded = jwt.encode(
            {
                "iss": _ISSUER,
                "aud": _AUDIENCE,
                "sub": str(user.id),
                "jti": str(uuid4()),
                "credential_version": user.credential_version,
                "purpose": _PURPOSE,
                "iat": int(now.timestamp()),
                "nbf": int(now.timestamp()),
                "exp": int(expires.timestamp()),
            },
            self.key,
            algorithm="EdDSA",
            headers={"typ": _TYPE, "kid": self.kid},
        )
        return FirstUserBearer(encoded, expires)

    def require(self, bearer: str) -> FirstUserToken:
        claims = require_pinned_current_user_token(
            bearer,
            pinned_public_key=self.key.public_key(),
            trusted_issuer=_ISSUER,
            trusted_audience=_AUDIENCE,
        )
        return FirstUserToken(
            claims.sub,
            claims.credential_version,
            claims.jti,
            datetime.fromtimestamp(claims.exp, UTC),
        )


@dataclass(frozen=True)
class SqlFirstUserLedger:
    database: PlatformDatabase
    pepper: bytes = field(repr=False)

    async def reserve(self, operation: UUID, username: str, source: str) -> UUID:
        digest = hmac.new(
            self.pepper, ("login:" + username.casefold() + ":" + source).encode(), hashlib.sha256
        ).hexdigest()
        receipt = uuid4()
        now = datetime.now(UTC)
        statement = (
            insert(OwnerCommandRow)
            .values(
                id=receipt,
                operation_uuid=operation,
                actor_scope="identity:preauth",
                project_scope="none",
                operation="identity.login",
                key=str(operation),
                fingerprint=digest,
                expected_owner_revision="identity-first-user-http-v1",
                state="pending",
                encrypted_outcome=None,
                created_at=now,
                updated_at=now,
                expires_at=now + timedelta(days=1),
            )
            .on_conflict_do_nothing()
            .returning(OwnerCommandRow.id)
        )
        async with self.database.transaction() as tx:
            if await tx.scalar(statement) is None:
                raise OriginalLoginUnavailable
        return receipt

    async def complete(self, receipt: UUID) -> None:
        async with self.database.transaction() as tx:
            changed = await tx.scalar(
                update(OwnerCommandRow)
                .where(OwnerCommandRow.id == receipt, OwnerCommandRow.state == "pending")
                .values(state="completed", updated_at=datetime.now(UTC))
                .returning(OwnerCommandRow.id)
            )
            if changed != receipt:
                raise OriginalLoginUnavailable


@dataclass(frozen=True)
class SqlFirstUserTransaction:
    tx: AsyncSession
    repository: IdentityRepository

    async def user(self, subject_id: UUID, *, lock: bool = False) -> CurrentUserSnapshot | None:
        row = await self.repository.get_user(self.tx, UserId(subject_id), lock=lock)
        if row is None:
            return None
        return CurrentUserSnapshot(row.enabled, row.deleted_at is not None, row.credential_version)

    async def revoked(self, jti: UUID) -> bool:
        return (
            await self.tx.scalar(
                select(AdminTokenRevocationRow.jti_digest).where(
                    AdminTokenRevocationRow.jti_digest == jti_digest(jti)
                )
            )
            is not None
        )

    async def revoke(self, token: FirstUserToken) -> None:
        await self.tx.execute(
            insert(AdminTokenRevocationRow)
            .values(
                jti_digest=jti_digest(token.jti),
                user_id=token.subject_id,
                expires_at=token.expires_at,
                revoked_at=datetime.now(UTC),
            )
            .on_conflict_do_nothing(index_elements=["jti_digest"])
        )


@dataclass(frozen=True)
class SqlFirstUserTransactions:
    database: PlatformDatabase
    repository: IdentityRepository

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[FirstUserTransaction]:
        async with self.database.transaction() as tx:
            yield SqlFirstUserTransaction(tx, self.repository)
