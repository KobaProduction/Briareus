"""Verify external OIDC JWT access tokens; this package never issues or stores user tokens."""

from __future__ import annotations

import asyncio
import time
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
from .roles import application_roles
from .settings import OidcTokenSettings


class TokenVerificationError(ValueError):
    """An external token is invalid or lacks the configured project grant."""


class _AccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)
    sub: str = Field(min_length=1)
    client_id: str = Field(validation_alias=AliasChoices("client_id", "azp"), min_length=1)
    azp: str | None = Field(default=None, min_length=1)
    exp: int
    nbf: int | None = None
    iat: int
    jti: str | None = Field(default=None, min_length=1)
    preferred_username: str = ""
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

    @property
    def jwks(self) -> PyJWKClient:
        return self._keys.client()

    async def verify_async(self, token: str) -> VerifiedPrincipal:
        return await asyncio.to_thread(self.verify, token)

    def verify(self, token: str) -> VerifiedPrincipal:
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
            claims = _AccessClaims.model_validate(payload)
            roles = application_roles(payload, self.settings)
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
