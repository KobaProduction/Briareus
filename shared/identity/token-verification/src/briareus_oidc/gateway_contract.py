"""Versioned, provider-neutral identity messages; never transport raw OIDC claims."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .verifier import TokenAccessDenied, TokenVerificationError, VerifiedPrincipal

INTERNAL_HOST = "gateway:8000"
INTERNAL_ORIGIN = "http://" + INTERNAL_HOST
METADATA_PATH = "/internal/identity/v1/metadata"
VERIFY_PATH = "/internal/identity/v1/verify"
MAX_MESSAGE_BYTES = 65536


class GatewayIdentityUnavailable(ValueError):
    """The private identity authority could not provide a verified result."""


class IdentityMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)


class GatewayMetadata(IdentityMessage):
    version: Literal[1]
    node_id: str = Field(min_length=1, max_length=200)
    public_origin: str = Field(min_length=1, max_length=2048)

    @field_validator("public_origin")
    @classmethod
    def validate_origin(cls, value: str) -> str:
        parsed = urlsplit(value)
        host = parsed.hostname or ""
        local = host in {"localhost", "127.0.0.1", "::1"} or host.endswith(".localhost")
        if (
            (parsed.scheme != "https" and not (parsed.scheme == "http" and local))
            or not host
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
            or value != value.strip()
            or value != f"{parsed.scheme}://{parsed.netloc}"
            or parsed.port == 0
        ):
            raise ValueError("Invalid Gateway public origin")
        return value


class VerifyRequest(IdentityMessage):
    token: str = Field(min_length=1, max_length=16384, repr=False)


class PrincipalMessage(IdentityMessage):
    version: Literal[1]
    node_id: str = Field(min_length=1, max_length=200)
    subject: str = Field(min_length=1, max_length=4096)
    username: str = Field(min_length=1, max_length=4096)
    display_name: str = Field(min_length=1, max_length=4096)
    roles: list[str] = Field(max_length=256)
    expires_at: int
    client_id: str = Field(min_length=1, max_length=4096)
    scopes: list[str] = Field(max_length=256)

    @classmethod
    def from_verified(cls, node_id: str, principal: VerifiedPrincipal) -> PrincipalMessage:
        return cls(
            version=1,
            node_id=node_id,
            subject=principal.subject,
            username=principal.username,
            display_name=principal.display_name,
            roles=list(principal.roles),
            expires_at=principal.expires_at,
            client_id=principal.client_id,
            scopes=list(principal.scopes),
        )

    def principal(self, expected_node: str) -> VerifiedPrincipal:
        if self.node_id != expected_node or expected_node not in self.roles:
            raise TokenAccessDenied
        result = VerifiedPrincipal(
            subject=self.subject,
            username=self.username,
            display_name=self.display_name,
            roles=tuple(self.roles),
            expires_at=self.expires_at,
            client_id=self.client_id,
            scopes=tuple(self.scopes),
            claims={},
        )
        if not result.is_active():
            raise TokenVerificationError(reason="expired")
        return result
