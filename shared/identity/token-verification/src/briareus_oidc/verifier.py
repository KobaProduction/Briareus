"""Verify external OIDC access tokens locally or through provider introspection."""

from __future__ import annotations

import asyncio
import hashlib
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Self

import httpx
import jwt
from briareus_json_values import JsonObject, json_object
from jwt import PyJWKClient
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    model_validator,
)

from .discovery import ProviderKeys
from .introspection import ProviderIntrospection
from .roles import application_roles
from .settings import OidcTokenSettings


class TokenVerificationError(ValueError):
    """An external token is invalid or lacks the configured project grant."""


class TokenAccessDenied(TokenVerificationError):
    """A verified access token lacks the application grant."""


class _AccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)
    sub: str = Field(min_length=1)
    client_id: str = Field(validation_alias=AliasChoices("client_id", "azp"), min_length=1)
    azp: str | None = Field(default=None, min_length=1)
    exp: int
    nbf: int | None = None
    iat: int
    jti: str | None = Field(default=None, min_length=1)
    preferred_username: str = Field(
        "", validation_alias=AliasChoices("preferred_username", "username")
    )
    name: str = ""
    scope: str = ""

    @model_validator(mode="after")
    def _consistent_client_identity(self) -> Self:
        if "azp" in self.model_fields_set and self.azp != self.client_id:
            raise ValueError("Conflicting OIDC client identity claims")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    subject: str
    username: str
    display_name: str
    roles: tuple[str, ...]
    expires_at: int
    client_id: str
    scopes: tuple[str, ...]
    claims: JsonObject = field(repr=False)

    def is_active(self) -> bool:
        return time.time() < self.expires_at


class OidcTokenVerifier:
    def __init__(self, settings: OidcTokenSettings) -> None:
        settings.validate_bootstrap()
        self.settings = settings
        self._keys = ProviderKeys(settings.issuer_url)
        self._introspection = ProviderIntrospection(settings)
        self._cache: OrderedDict[str, tuple[float, VerifiedPrincipal]] = OrderedDict()
        self._cache_lock = threading.Lock()

    @property
    def jwks(self) -> PyJWKClient:
        return self._keys.client()

    async def verify_async(self, token: str) -> VerifiedPrincipal:
        return await asyncio.to_thread(self.verify, token)

    def verify(self, token: str) -> VerifiedPrincipal:
        if not token or len(token) > 16384:
            raise TokenVerificationError("Invalid or unauthorized OIDC access token")
        if self.settings.token_verification == "introspection":
            return self._introspected(token)
        return self._principal(self._jwt_payload(token))

    def _jwt_payload(self, token: str) -> JsonObject:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.settings.algorithms:
                raise TokenVerificationError("Unsupported OIDC signing algorithm")
            key = self.jwks.get_signing_key_from_jwt(token)
            payload = json_object(
                jwt.decode(
                    token,
                    key.key,
                    algorithms=list(self.settings.algorithms),
                    audience=self.settings.resolved_audience,
                    issuer=self.settings.issuer_url,
                    options={"require": ["exp", "iat", "iss", "aud", "sub"]},
                )
            )
        except (
            jwt.PyJWTError,
            ValidationError,
            ValueError,
            TypeError,
            OverflowError,
            OSError,
            httpx.HTTPError,
        ) as exc:
            # No bearer text, provider payload or cryptographic exception reaches logs/responses.
            raise TokenVerificationError("Invalid or unauthorized OIDC access token") from exc
        return payload

    def _introspected(self, token: str) -> VerifiedPrincipal:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._cache_lock:
            cached = self._cache.get(digest)
            if cached is not None and cached[0] > time.monotonic() and cached[1].is_active():
                self._cache.move_to_end(digest)
                return cached[1]
            self._cache.pop(digest, None)
            try:
                payload = self._introspection.verify(token)
                self._validate_introspection(payload)
            except (ValueError, TypeError, OSError, httpx.HTTPError) as exc:
                raise TokenVerificationError("Invalid or unauthorized OIDC access token") from exc
            principal = self._principal(payload)
            self._cache[digest] = (time.monotonic() + 30, principal)
            if len(self._cache) > 256:
                self._cache.popitem(last=False)
            return principal

    def _validate_introspection(self, payload: JsonObject) -> None:
        audience = payload.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if (
            payload.get("iss") != self.settings.issuer_url
            or not isinstance(audiences, list)
            or self.settings.resolved_audience not in audiences
        ):
            raise ValueError("OIDC issuer or audience mismatch")
        claims = _AccessClaims.model_validate(payload)
        now = time.time()
        if claims.exp <= now or claims.iat > now or (claims.nbf is not None and claims.nbf > now):
            raise ValueError("OIDC token outside its validity period")

    def _principal(self, payload: JsonObject) -> VerifiedPrincipal:
        try:
            claims = _AccessClaims.model_validate(payload)
        except ValidationError as exc:
            raise TokenVerificationError("Invalid or unauthorized OIDC access token") from exc
        try:
            roles = application_roles(payload, self.settings)
        except (ValueError, TypeError) as exc:
            raise TokenAccessDenied("OIDC application access denied") from exc
        return VerifiedPrincipal(
            subject=claims.sub,
            username=claims.preferred_username or claims.sub,
            display_name=claims.name or claims.preferred_username or claims.sub,
            roles=roles,
            expires_at=claims.exp,
            client_id=claims.client_id,
            scopes=tuple(claims.scope.split()),
            claims=payload,
        )
