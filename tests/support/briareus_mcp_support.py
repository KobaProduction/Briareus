"""Local OAuth authority fixtures using real signing and durable encrypted adapters."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass
from pathlib import Path

from auth_service.identity import oauth_storage
from auth_service.provider import MultiResourceZitadelProvider
from auth_service.token_status import LocalTokenAuthority
from briareus_identity.identity_settings import McpAuthSettings, ZitadelSettings
from briareus_mcp_resources import allowed_resource_urls
from briareus_support import ISSUER, ORIGIN, SUBJECT
from fastmcp.server.auth.jwt_issuer import JWTIssuer, derive_jwt_key
from fastmcp.server.auth.oauth_proxy.models import (
    JTIMapping,
    RefreshTokenMetadata,
    UpstreamTokenSet,
)
from key_value.aio.adapters.pydantic import PydanticAdapter
from pydantic import AnyHttpUrl


@dataclass(frozen=True)
class IssuedFamily:
    access: str
    refresh: str
    client_id: str
    resource: str
    upstream_id: str


class McpAuthorityHarness:
    def __init__(self, directory: Path) -> None:
        self.settings = McpAuthSettings(
            public_base_url=ORIGIN,
            oauth_jwt_signing_key="test-replay-store-key",
            state_directory=directory,
            introspection_token="test-private-status-key",
        )
        self.identity = ZitadelSettings(
            issuer_url=ISSUER,
            client_id="provider-client",
            client_secret="test-client-secret",
            allowed_subjects=(SUBJECT,),
        )
        self.storage = oauth_storage(self.settings)
        self.mappings = PydanticAdapter[JTIMapping](
            key_value=self.storage,
            pydantic_model=JTIMapping,
            default_collection="test-briareus-jtis",
            raise_on_validation_error=True,
        )
        self.upstream = PydanticAdapter[UpstreamTokenSet](
            key_value=self.storage,
            pydantic_model=UpstreamTokenSet,
            default_collection="test-briareus-upstream",
            raise_on_validation_error=True,
        )
        self.refresh_metadata = PydanticAdapter[RefreshTokenMetadata](
            key_value=self.storage,
            pydantic_model=RefreshTokenMetadata,
            default_collection="test-briareus-refresh-metadata",
            raise_on_validation_error=True,
        )
        signing_key = derive_jwt_key(
            low_entropy_material=self.settings.resolved_signing_key,
            salt="fastmcp-jwt-signing-key",
        )
        self.issuers = {
            resource: JWTIssuer(
                issuer=str(AnyHttpUrl(ORIGIN)), audience=resource, signing_key=signing_key
            )
            for resource in allowed_resource_urls(ORIGIN)
        }
        self.authority = LocalTokenAuthority(
            storage=self.storage,
            mappings=self.mappings,
            upstream_tokens=self.upstream,
            audience_for_token=MultiResourceZitadelProvider._jwt_audience_unverified,
            canonical_resource=self.canonical_resource,
            issuer_for_resource=self.issuer,
            identity=self.identity,
        )
        self.counter = 0

    def canonical_resource(self, resource: str | None) -> str:
        if resource not in self.issuers:
            raise ValueError("Unknown MCP resource")
        assert resource is not None
        return resource

    def issuer(self, resource: str | None) -> JWTIssuer:
        return self.issuers[self.canonical_resource(resource)]

    async def issue(
        self,
        *,
        client_id: str = "test-client",
        resource: str = ORIGIN + "/server/mcp",
        upstream_id: str = "upstream-family-A",
    ) -> IssuedFamily:
        self.counter += 1
        now = time.time()
        await self.upstream.put(
            key=upstream_id,
            value=UpstreamTokenSet(
                upstream_token_id=upstream_id,
                access_token="test-upstream-access",
                refresh_token="test-upstream-refresh",
                refresh_token_expires_at=now + 600,
                expires_at=now + 300,
                token_type="Bearer",
                scope="openid",
                client_id=client_id,
                created_at=now,
            ),
        )
        access_jti, refresh_jti = f"access-{self.counter}", f"refresh-{self.counter}"
        for jti in (access_jti, refresh_jti):
            await self.mappings.put(
                key=jti,
                value=JTIMapping(
                    jti=jti,
                    upstream_token_id=upstream_id,
                    created_at=now,
                ),
            )
        claims = {"iss": ISSUER, "sub": SUBJECT, "identity_provider": "zitadel"}
        issuer = self.issuer(resource)
        access = issuer.issue_access_token(
            client_id=client_id,
            scopes=["openid"],
            jti=access_jti,
            expires_in=300,
            upstream_claims=claims,
        )
        refresh = issuer.issue_refresh_token(
            client_id=client_id,
            scopes=["openid"],
            jti=refresh_jti,
            expires_in=600,
            upstream_claims=claims,
        )
        await self.refresh_metadata.put(
            key=hashlib.sha256(refresh.encode()).hexdigest(),
            value=RefreshTokenMetadata(
                client_id=client_id,
                scopes=["openid"],
                expires_at=int(now + 600),
                created_at=now,
            ),
        )
        return IssuedFamily(access, refresh, client_id, resource, upstream_id)
