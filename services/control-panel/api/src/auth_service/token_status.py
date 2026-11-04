"""Local durable OAuth family authority; never polls the upstream identity provider."""

from __future__ import annotations

import hashlib
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal

from briareus_identity.identity_settings import ZitadelSettings
from fastmcp.server.auth.jwt_issuer import JWTIssuer
from fastmcp.server.auth.oauth_proxy.models import JTIMapping, UpstreamTokenSet
from joserfc.errors import JoseError
from key_value.aio.adapters.pydantic import PydanticAdapter
from key_value.aio.protocols import AsyncKeyValue
from pydantic import BaseModel, ConfigDict, Field


class UpstreamIdentityClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")
    iss: str
    sub: str = Field(min_length=1)
    identity_provider: str


class VerifiedTokenClaims(BaseModel):
    model_config = ConfigDict(extra="ignore")
    iss: str
    aud: str
    client_id: str = Field(min_length=1)
    jti: str = Field(min_length=1)
    exp: int
    scope: str = ""
    upstream_claims: UpstreamIdentityClaims | None = None


class RevokedFamily(BaseModel):
    model_config = ConfigDict(extra="forbid")
    client_id: str
    resource: str
    upstream_token_id: str
    revoked_at: float


class LocalTokenStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")
    active: bool
    client_id: str | None = None
    sub: str | None = None
    scope: str | None = None
    aud: str | None = None
    iss: str | None = None
    exp: int | None = None


@dataclass(frozen=True)
class TokenFamily:
    claims: VerifiedTokenClaims
    upstream_token_id: str

    @property
    def key(self) -> str:
        binding = f"{self.claims.client_id}\0{self.claims.aud}\0{self.upstream_token_id}"
        return hashlib.sha256(binding.encode()).hexdigest()


class LocalTokenAuthority:
    def __init__(
        self,
        *,
        storage: AsyncKeyValue,
        mappings: PydanticAdapter[JTIMapping],
        upstream_tokens: PydanticAdapter[UpstreamTokenSet],
        audience_for_token: Callable[[str], str | None],
        canonical_resource: Callable[[str | None], str],
        issuer_for_resource: Callable[[str | None], JWTIssuer],
        identity: ZitadelSettings,
        revocation_collection: str = "briareus-oauth-revoked-families",
    ) -> None:
        self.mappings = mappings
        self.upstream_tokens = upstream_tokens
        self.audience_for_token = audience_for_token
        self.canonical_resource = canonical_resource
        self.issuer_for_resource = issuer_for_resource
        self.identity = identity
        self.revocations = PydanticAdapter[RevokedFamily](
            key_value=storage,
            pydantic_model=RevokedFamily,
            default_collection=revocation_collection,
            raise_on_validation_error=True,
        )

    def verified_claims(
        self, token: str, token_use: Literal["access", "refresh"]
    ) -> VerifiedTokenClaims | None:
        try:
            resource = self.canonical_resource(self.audience_for_token(token))
            payload = self.issuer_for_resource(resource).verify_token(
                token, expected_token_use=token_use
            )
            return VerifiedTokenClaims.model_validate(payload)
        except (JoseError, ValueError, KeyError):
            return None

    async def resolve(
        self, token: str, token_use: Literal["access", "refresh"]
    ) -> TokenFamily | None:
        claims = self.verified_claims(token, token_use)
        if claims is None:
            return None
        mapping = await self.mappings.get(key=claims.jti)
        if mapping is None or mapping.jti != claims.jti:
            return None
        upstream = await self.upstream_tokens.get(key=mapping.upstream_token_id)
        if (
            upstream is None
            or upstream.client_id != claims.client_id
            or upstream.upstream_token_id != mapping.upstream_token_id
        ):
            return None
        return TokenFamily(claims, mapping.upstream_token_id)

    async def is_active(self, family: TokenFamily) -> bool:
        return (
            family.claims.exp > time.time() and await self.revocations.get(key=family.key) is None
        )

    async def refresh_allowed(self, token: str, client_id: str) -> bool:
        family = await self.resolve(token, "refresh")
        if family is None or family.claims.client_id != client_id:
            return False
        return await self.is_active(family)

    async def revoke(
        self,
        token: str,
        token_use: Literal["access", "refresh"],
        client_id: str,
    ) -> TokenFamily | None:
        family = await self.resolve(token, token_use)
        if family is None or family.claims.client_id != client_id:
            return None
        return await self.revoke_family(family, client_id)

    async def revoke_family(self, family: TokenFamily, client_id: str) -> TokenFamily | None:
        if family.claims.client_id != client_id:
            return None
        await self.revocations.put(
            key=family.key,
            value=RevokedFamily(
                client_id=client_id,
                resource=family.claims.aud,
                upstream_token_id=family.upstream_token_id,
                revoked_at=time.time(),
            ),
        )
        return family

    async def access_family(self, token: str) -> TokenFamily | None:
        family = await self.resolve(token, "access")
        if family is None or not await self.is_active(family):
            return None
        claims = family.claims
        upstream = claims.upstream_claims
        if (
            upstream is None
            or upstream.identity_provider != "zitadel"
            or upstream.iss != self.identity.canonical_issuer
            or upstream.sub not in self.identity.allowed_subjects
            or "openid" not in claims.scope.split()
        ):
            return None
        return family

    async def status(self, token: str) -> LocalTokenStatus:
        family = await self.access_family(token)
        if family is None:
            return LocalTokenStatus(active=False)
        claims = family.claims
        upstream = claims.upstream_claims
        if upstream is None:
            return LocalTokenStatus(active=False)
        return LocalTokenStatus(
            active=True,
            client_id=claims.client_id,
            sub=upstream.sub,
            scope=claims.scope,
            aud=claims.aud,
            iss=claims.iss,
            exp=claims.exp,
        )
