"""Authoritative current User/JTI verifier in Identity's OWN PostgreSQL.

No Admin/API/Gateway SQL access, unsigned proxy-user header, or arbitrary JWT
claim object grants an account. Requires its own current mTLS/Unix peer
verification, pinned Ed25519 bearer and fresh Identity row/revocation checks.
Source-only: never registered on the published default ASGI application.
"""

from __future__ import annotations

from uuid import UUID

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import SecretStr

from common.owner_bff_models import VerifiedAdminCaller
from common.owner_contracts import (
    TrustedOwnerServicePeerPort,
)
from common.platform_db import PlatformDatabase
from common.private_user_token import (
    IdentityCredentialRejected,
)
from identity._repository import IdentityRepository
from identity.application.current_user import RequireLegacyCurrentUser
from identity.infrastructure.current_user import (
    CurrentIdentityPeer,
    PinnedIdentityBearer,
    SqlCurrentUserTransactions,
    require_current_source_configuration,
)


class IdentityCurrentUserSource:
    """Fresh owner-local current User source, never a bearer issuer."""

    def __init__(
        self,
        *,
        database: PlatformDatabase,
        peer_verifier: TrustedOwnerServicePeerPort,
        bearer_public_key: Ed25519PublicKey,
        trusted_issuer: str,
        trusted_audience: str,
        admin_service_id: UUID,
        admin_instance_uuid: UUID,
    ) -> None:
        require_current_source_configuration(
            database,
            peer_verifier,
            bearer_public_key,
            trusted_issuer,
            trusted_audience,
            admin_service_id,
            admin_instance_uuid,
        )
        self.db = database
        self.peers = peer_verifier
        self.key = bearer_public_key
        self.issuer = trusted_issuer
        self.audience = trusted_audience
        self.admin_service_id = admin_service_id
        self.admin_instance_uuid = admin_instance_uuid
        self.repo = IdentityRepository()

    async def require_current(
        self, *, bearer: SecretStr, peer_evidence: object
    ) -> VerifiedAdminCaller:
        return await RequireLegacyCurrentUser(
            CurrentIdentityPeer(self.peers, self.admin_service_id, self.admin_instance_uuid),
            PinnedIdentityBearer(self.key, self.issuer, self.audience),
            SqlCurrentUserTransactions(self.db, self.repo),
        ).execute(bearer, peer_evidence)


def build_unmounted_identity_current_router(source: IdentityCurrentUserSource) -> APIRouter:
    """Internal status only, and only with an actual attested C2 source."""
    if not isinstance(source, IdentityCurrentUserSource):
        raise ValueError("trusted Identity reader required")
    router = APIRouter(prefix="/internal/v1/identity", tags=["identity-current-private"])

    @router.post("/current", response_model=VerifiedAdminCaller)
    async def current_user(request: Request, response: Response) -> VerifiedAdminCaller:
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        authorization = request.headers.get("authorization", "")
        if (
            not authorization.startswith("Bearer ")
            or authorization.count(" ") != 1
            or request.headers.get("cookie") is not None
        ):
            raise HTTPException(401, detail="current signed User bearer required")
        try:
            return await source.require_current(
                bearer=SecretStr(authorization[7:]), peer_evidence=request
            )
        except IdentityCredentialRejected:
            raise HTTPException(401, detail="current Identity user not authorized") from None
        except Exception:
            raise HTTPException(503, detail="current Identity source unavailable") from None

    return router
