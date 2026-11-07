"""Verify external ZITADEL JWTs; this package never issues or stores user tokens."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Self

import jwt
from briareus_json_values import JsonObject, json_object
from jwt import PyJWKClient
from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from .settings import ZitadelTokenSettings

type OrganizationGrants = dict[str, str]
type ProjectRoles = dict[str, OrganizationGrants]
_ROLE_CLAIMS: TypeAdapter[ProjectRoles | list[ProjectRoles]] = TypeAdapter(
    ProjectRoles | list[ProjectRoles]
)


class TokenVerificationError(ValueError):
    """An external token is invalid or lacks the configured project grant."""


class _AccessClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, populate_by_name=True)
    sub: str = Field(min_length=1)
    client_id: str = Field(validation_alias=AliasChoices("client_id", "azp"), min_length=1)
    azp: str | None = Field(default=None, min_length=1)
    exp: int
    nbf: int
    iat: int
    jti: str = Field(min_length=1)
    preferred_username: str = ""
    name: str = ""
    scope: str = ""

    @model_validator(mode="after")
    def _consistent_client_identity(self) -> Self:
        if "azp" in self.model_fields_set and self.azp != self.client_id:
            raise ValueError("Conflicting ZITADEL client identity claims")
        return self


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    subject: str
    username: str
    display_name: str
    organization_id: str
    project_id: str
    roles: tuple[str, ...]
    expires_at: int
    client_id: str
    scopes: tuple[str, ...]
    claims: JsonObject = field(repr=False)

    def is_active(self) -> bool:
        return time.time() < self.expires_at


class ZitadelTokenVerifier:
    def __init__(self, settings: ZitadelTokenSettings) -> None:
        settings.validate_bootstrap()
        self.settings = settings
        # Cache JWKS sets, not individual keys indefinitely: removed keys expire with this TTL.
        self.jwks = PyJWKClient(
            settings.issuer_url.rstrip("/") + "/oauth/v2/keys",
            cache_keys=False,
            cache_jwk_set=True,
            lifespan=300,
            timeout=5,
        )

    async def verify_async(self, token: str) -> VerifiedPrincipal:
        return await asyncio.to_thread(self.verify, token)

    def verify(self, token: str) -> VerifiedPrincipal:
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") not in self.settings.algorithms:
                raise TokenVerificationError("Unsupported ZITADEL signing algorithm")
            key = self.jwks.get_signing_key_from_jwt(token)
            payload = json_object(
                jwt.decode(
                    token,
                    key.key,
                    algorithms=list(self.settings.algorithms),
                    audience=self.settings.resolved_audience,
                    issuer=self.settings.issuer_url,
                    options={"require": ["exp", "nbf", "iat", "iss", "aud", "sub", "jti"]},
                )
            )
            claims = _AccessClaims.model_validate(payload)
            roles = self._roles(payload)
        except (jwt.PyJWTError, ValidationError, ValueError, OSError) as exc:
            # No bearer text, provider payload or cryptographic exception reaches logs/responses.
            raise TokenVerificationError("Invalid or unauthorized ZITADEL access token") from exc
        return VerifiedPrincipal(
            subject=claims.sub,
            username=claims.preferred_username or claims.sub,
            display_name=claims.name or claims.preferred_username or claims.sub,
            organization_id=self.settings.organization_id,
            project_id=self.settings.project_id,
            roles=roles,
            expires_at=claims.exp,
            client_id=claims.client_id,
            scopes=tuple(claims.scope.split()),
            claims=payload,
        )

    def _roles(self, payload: JsonObject) -> tuple[str, ...]:
        grants = _ROLE_CLAIMS.validate_python(payload.get(self.settings.roles_claim), strict=True)
        groups = grants if isinstance(grants, list) else [grants]
        roles = {
            role
            for group in groups
            for role, organizations in group.items()
            if organizations.get(self.settings.organization_id)
        }
        if "access" not in roles:
            raise TokenVerificationError("Required ZITADEL project/organization role is absent")
        return tuple(sorted(roles))
