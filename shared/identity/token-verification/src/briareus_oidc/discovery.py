"""Discover and cache provider keys without hard-coded vendor endpoints."""

from __future__ import annotations

import threading
import time

import httpx
from jwt import PyJWKClient
from pydantic import BaseModel, ConfigDict

from .settings import secure_provider_url


class ProviderMetadata(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True)
    issuer: str
    jwks_uri: str
    introspection_endpoint: str = ""


def discover(issuer: str) -> ProviderMetadata:
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.stream("GET", url, timeout=5, follow_redirects=False) as response:
        response.raise_for_status()
        content = bytearray()
        for chunk in response.iter_bytes():
            content.extend(chunk)
            if len(content) > 65536:
                raise ValueError("OIDC discovery document exceeds the size limit")
    metadata = ProviderMetadata.model_validate_json(bytes(content))
    if metadata.issuer != issuer:
        raise ValueError("OIDC discovery issuer does not match the configured issuer")
    secure_provider_url(metadata.jwks_uri)
    return metadata


class ProviderKeys:
    def __init__(self, issuer: str) -> None:
        self.issuer = issuer
        self._client: PyJWKClient | None = None
        self._uri = ""
        self._expires = 0.0
        self._lock = threading.Lock()

    def client(self) -> PyJWKClient:
        with self._lock:
            if self._client is None or time.monotonic() >= self._expires:
                metadata = discover(self.issuer)
                if self._client is None or self._uri != metadata.jwks_uri:
                    self._client = PyJWKClient(
                        metadata.jwks_uri,
                        cache_keys=False,
                        cache_jwk_set=True,
                        lifespan=300,
                        timeout=5,
                    )
                    self._uri = metadata.jwks_uri
                self._expires = time.monotonic() + 300
            return self._client
