"""Legacy private login admission, bearer contracts and bounded application scenarios."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, TypeGuard
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SecretStr

from common.owner_contracts import VerifiedOwnerServicePeer
from common.platform_errors import AuthenticationRateLimited, AuthenticationRequired
from identity._domain import User

_MAX_TTL = timedelta(minutes=15)


def _verified_service_peer(value: object) -> TypeGuard[VerifiedOwnerServicePeer]:
    return isinstance(value, VerifiedOwnerServicePeer)


class IdentitySourceUnavailable(RuntimeError):
    """Original password/session source unavailable; never infer invalid credentials."""


@dataclass(frozen=True, slots=True)
class VerifiedIdentityLoginAdmission:
    """Produced by the physical C2 edge, NOT by Host/Origin/Forwarded strings."""

    recipient: VerifiedOwnerServicePeer
    browser_origin: str
    source_fingerprint: str
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            not _verified_service_peer(self.recipient)
            or self.recipient.audience != "briareus:identity"
            or self.browser_origin != "https://briareus.koba-nexus.ru"
            or len(self.source_fingerprint) != 64
            or any(x not in "0123456789abcdef" for x in self.source_fingerprint)
            or self.expires_at.tzinfo is None
            or not datetime.now(UTC) < self.expires_at <= self.recipient.expires_at
        ):
            raise ValueError("Identity login requires genuine browser and C2 source")


class TrustedIdentityLoginAdmissionPort(Protocol):
    async def require_browser_and_peer(self, *, evidence: object) -> VerifiedIdentityLoginAdmission:
        """Verify real TLS Host/Origin and registered mTLS/Unix service peer.

        Produce a stable non-reversible rate-limit source fingerprint from
        verified connection data, not a user-controlled X-Forwarded-For.
        """
        ...


class IssuedIdentityBearer(BaseModel):
    """Return only a real issuer-signed, pinned, short-lived User session."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    token: SecretStr
    subject_user_id: UUID
    jti: UUID
    credential_version: int = Field(ge=1)
    issuer: str = Field(min_length=1, max_length=160)
    audience: str = Field(min_length=1, max_length=160)
    issued_at: datetime
    expires_at: datetime

    def require_current_shape(self, user: User, *, issuer: str, audience: str) -> None:
        now = datetime.now(UTC)
        if (
            self.subject_user_id != user.id
            or self.subject_user_id.version != 4
            or self.jti.version != 4
            or self.credential_version != user.credential_version
            or self.issuer != issuer
            or self.audience != audience
            or self.issued_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or not self.issued_at <= now < self.expires_at
            or self.expires_at - self.issued_at > _MAX_TTL
            or not 40 <= len(self.token.get_secret_value()) <= 8192
        ):
            raise AuthenticationRequired("source-signed Identity login claims unavailable")


class TrustedIdentitySessionIssuer(Protocol):
    async def issue_for_current_user(
        self, *, user: User, admission: VerifiedIdentityLoginAdmission
    ) -> IssuedIdentityBearer:
        """Pin issuer/audience and reserve JTI in actual Identity owner DB.

        Recheck current User enabled/deleted and credential version before
        issuing, not merely trust a stale password verification result.
        """
        ...

    async def require_current(
        self,
        *,
        issued: IssuedIdentityBearer,
        admission: VerifiedIdentityLoginAdmission,
    ) -> None:
        """Cryptographically verify token and reread current User+JTI denylist."""
        ...

    async def revoke_user_token(
        self, *, bearer: SecretStr, admission: VerifiedIdentityLoginAdmission
    ) -> None:
        """Revoke one valid signed JTI in Identity owner SQL, never in Gateway."""
        ...


class LegacyPasswordAuthentication(Protocol):
    async def authenticate_limited(
        self, username: str, password: str, *, source: str, pepper: bytes
    ) -> User | None: ...


class OriginalLoginLedger(Protocol):
    async def _reserve_original_login(
        self,
        *,
        original_uuid: UUID,
        username: str,
        password: SecretStr,
        admission: VerifiedIdentityLoginAdmission,
    ) -> UUID: ...

    async def _complete_original_login(self, receipt_id: UUID) -> None: ...


@dataclass(frozen=True)
class PrivateIdentityLogin:
    identity: LegacyPasswordAuthentication
    ingress: TrustedIdentityLoginAdmissionPort
    tokens: TrustedIdentitySessionIssuer
    ledger: OriginalLoginLedger
    issuer: str
    audience: str
    identity_login_pepper: bytes

    async def login(
        self,
        *,
        evidence: object,
        username: str,
        password: SecretStr,
        original_uuid: UUID,
    ) -> IssuedIdentityBearer:
        if not 3 <= len(username) <= 128 or not 12 <= len(password.get_secret_value()) <= 4096:
            raise AuthenticationRequired("valid Identity login required")
        try:
            async with asyncio.timeout(5):
                admission = await self.ingress.require_browser_and_peer(evidence=evidence)
                if not isinstance(admission, VerifiedIdentityLoginAdmission):
                    raise AuthenticationRequired("Identity login source is not authenticated")
                user = await self.identity.authenticate_limited(
                    username,
                    password.get_secret_value(),
                    source=admission.source_fingerprint,
                    pepper=self.identity_login_pepper,
                )
                if user is None or not user.enabled:
                    raise AuthenticationRequired("invalid Identity credentials")
                receipt_id = await self.ledger._reserve_original_login(
                    original_uuid=original_uuid,
                    username=username,
                    password=password,
                    admission=admission,
                )
                issued = await self.tokens.issue_for_current_user(user=user, admission=admission)
                issued.require_current_shape(user, issuer=self.issuer, audience=self.audience)
                await self.tokens.require_current(issued=issued, admission=admission)
                await self.ledger._complete_original_login(receipt_id)
                return issued
        except (AuthenticationRequired, AuthenticationRateLimited):
            raise
        except Exception:
            raise IdentitySourceUnavailable("current Identity login source unavailable") from None

    async def logout(self, *, evidence: object, bearer: SecretStr) -> None:
        if not 40 <= len(bearer.get_secret_value()) <= 8192:
            raise AuthenticationRequired("current Identity bearer required")
        try:
            async with asyncio.timeout(5):
                admission = await self.ingress.require_browser_and_peer(evidence=evidence)
                if not isinstance(admission, VerifiedIdentityLoginAdmission):
                    raise AuthenticationRequired("verified Identity logout peer required")
                await self.tokens.revoke_user_token(bearer=bearer, admission=admission)
        except AuthenticationRequired:
            raise
        except Exception:
            raise IdentitySourceUnavailable("Identity logout source unavailable") from None
