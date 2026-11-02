"""Pinned peer/token verification and owner-local current User/JTI SQL."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TypeGuard
from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.owner_contracts import (
    OwnerAuthorityUnavailable,
    TrustedOwnerServicePeerPort,
    VerifiedOwnerServicePeer,
)
from common.platform_db import PlatformDatabase
from common.platform_ids import UserId
from common.private_user_token import (
    IdentityCredentialRejected,
    jti_digest,
    require_pinned_current_user_token,
)
from identity._persistence import AdminTokenRevocationRow
from identity._repository import IdentityRepository
from identity.application.current_user import CurrentIdentityToken, CurrentUserTransaction
from identity.domain.current_user import CurrentUserSnapshot


def require_current_source_configuration(
    database: PlatformDatabase,
    peer_verifier: object,
    bearer_public_key: object,
    trusted_issuer: str,
    trusted_audience: str,
    admin_service_id: UUID,
    admin_instance_uuid: UUID,
) -> None:
    if (
        database.engine.url.database != "briareus_identity"
        or peer_verifier is None
        or not isinstance(bearer_public_key, Ed25519PublicKey)
        or not trusted_issuer.startswith("briareus:")
        or not trusted_audience.startswith("briareus:")
        or admin_service_id.version != 4
        or admin_instance_uuid.version != 4
    ):
        raise ValueError("Identity current User requires scoped DB, release pin and peer")


def _verified_peer(value: object) -> TypeGuard[VerifiedOwnerServicePeer]:
    return isinstance(value, VerifiedOwnerServicePeer)


def _secret_bearer(value: object) -> TypeGuard[SecretStr]:
    return isinstance(value, SecretStr)


@dataclass(frozen=True)
class CurrentIdentityPeer:
    peers: TrustedOwnerServicePeerPort
    admin_service_id: UUID
    admin_instance_uuid: UUID

    def require(self, evidence: object) -> None:
        try:
            peer = self.peers.verify_peer(evidence)
        except Exception:
            raise OwnerAuthorityUnavailable("Identity private C2 peer not attested") from None
        if (
            not _verified_peer(peer)
            or peer.service_id != self.admin_service_id
            or peer.instance_uuid != self.admin_instance_uuid
            or peer.audience != "briareus:identity"
            or peer.expires_at <= datetime.now(UTC)
        ):
            raise OwnerAuthorityUnavailable("wrong Identity status source recipient")


@dataclass(frozen=True)
class PinnedIdentityBearer:
    key: Ed25519PublicKey
    issuer: str
    audience: str

    def require(self, bearer: SecretStr) -> CurrentIdentityToken:
        if not _secret_bearer(bearer):
            raise IdentityCredentialRejected("current signed Identity bearer required")
        try:
            claims = require_pinned_current_user_token(
                bearer.get_secret_value(),
                pinned_public_key=self.key,
                trusted_issuer=self.issuer,
                trusted_audience=self.audience,
            )
        except OwnerAuthorityUnavailable:
            raise IdentityCredentialRejected("signed Identity bearer rejected") from None
        return CurrentIdentityToken(claims.sub, claims.jti, claims.credential_version)


@dataclass(frozen=True)
class SqlCurrentUserTransaction:
    tx: AsyncSession
    repository: IdentityRepository

    async def user(self, subject_id: UUID) -> CurrentUserSnapshot | None:
        row = await self.repository.get_user(self.tx, UserId(subject_id))
        if row is None:
            return None
        return CurrentUserSnapshot(row.enabled, row.deleted_at is not None, row.credential_version)

    async def revoked(self, jti: UUID) -> bool:
        revoked = await self.tx.scalar(
            select(AdminTokenRevocationRow.jti_digest).where(
                AdminTokenRevocationRow.jti_digest == jti_digest(jti)
            )
        )
        return revoked is not None


@dataclass(frozen=True)
class SqlCurrentUserTransactions:
    database: PlatformDatabase
    repository: IdentityRepository

    @asynccontextmanager
    async def __call__(self) -> AsyncIterator[CurrentUserTransaction]:
        async with self.database.transaction() as tx:
            yield SqlCurrentUserTransaction(tx, self.repository)
