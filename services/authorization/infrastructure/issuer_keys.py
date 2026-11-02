"""Trusted discovery and key refresh composition."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from time import monotonic

from pydantic import BaseModel

from authorization.application.issuer_keys import RefreshIssuerKeys
from authorization.domain.rauthy import RauthyKeysUnavailable, TrustedIssuer
from authorization.infrastructure.issuer_documents import authority_document, read_json_https
from authorization.infrastructure.rauthy_tokens import RauthyJwksVerifier
from runtime_peer.oidc_wire import IssuerDiscovery, IssuerSigningKeys


def trusted_jwks_url(issuer: str, metadata: IssuerDiscovery) -> str:
    return TrustedIssuer(issuer).signing_keys_uri(metadata.issuer, metadata.jwks_uri)


class _IssuerKeyLoader:
    def __init__(
        self,
        issuer: str,
        resource_audience: str,
        oauth_client_id: str,
        fetch: Callable[[str, int], bytes] | None,
    ) -> None:
        self._issuer = issuer
        self._audience = resource_audience
        self._client_id = oauth_client_id
        self._fetch = fetch

    def _document[DocumentT: BaseModel](
        self, url: str, maximum: int, schema: type[DocumentT]
    ) -> DocumentT:
        payload = (
            read_json_https(url, max_bytes=maximum)
            if self._fetch is None
            else self._fetch(url, maximum)
        )
        if len(payload) > maximum:
            raise RauthyKeysUnavailable("Rauthy issuer response exceeded byte limit")
        return authority_document(payload, schema)

    def _load(self) -> RauthyJwksVerifier:
        discovery = self._document(
            self._issuer + ".well-known/openid-configuration", 16384, IssuerDiscovery
        )
        uri = trusted_jwks_url(self._issuer, discovery)
        keys = self._document(uri, 65536, IssuerSigningKeys)
        return RauthyJwksVerifier(
            issuer=self._issuer,
            resource_audience=self._audience,
            oauth_client_id=self._client_id,
            trusted_jwks=keys,
        )

    async def load(self) -> RauthyJwksVerifier:
        return await asyncio.to_thread(self._load)


class TrustedRauthyIssuerKeys:
    """Cache issuer-approved keys; a failed refresh expires closed."""

    def __init__(
        self,
        *,
        issuer: str,
        resource_audience: str,
        oauth_client_id: str,
        ttl_seconds: float = 300.0,
        json_fetch: Callable[[str, int], bytes] | None = None,
    ) -> None:
        trusted = TrustedIssuer(issuer)
        loader = _IssuerKeyLoader(trusted.issuer, resource_audience, oauth_client_id, json_fetch)
        self._refresh = RefreshIssuerKeys(loader, asyncio.Lock(), monotonic, ttl_seconds)

    async def get_verifier(self) -> RauthyJwksVerifier:
        return await self._refresh.execute()
