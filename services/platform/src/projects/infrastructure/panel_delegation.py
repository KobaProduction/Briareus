"""Decode only signature-verified Panel service JWTs into explicit wire fields."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, model_validator

from projects.domain.context import ContextSelector, VerifiedPanelContextPeer


class PanelDelegationHeader(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    typ: Literal["briareus-panel-delegation+jwt"]
    crit: list[str] | None = None

    @model_validator(mode="after")
    def no_unsupported_critical_headers(self) -> "PanelDelegationHeader":
        if self.crit:
            raise ValueError("Invalid delegation header")
        return self


class PanelDelegationClaims(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    issuer: Literal["briareus:control-panel-api"] = Field(alias="iss")
    audience: Literal["briareus:platform"] = Field(alias="aud")
    subject: str = Field(alias="sub")
    issued_at: int = Field(alias="iat")
    not_before: int = Field(alias="nbf")
    expires_at: int = Field(alias="exp")
    nonce: str = Field(alias="jti")
    purpose: str
    rauthy_issuer: str
    project_uuid: str | None
    command_digest: str | None = None

    @model_validator(mode="after")
    def bounded_delegation(self) -> "PanelDelegationClaims":
        if not 0 < self.expires_at - self.issued_at <= 15 or UUID(self.nonce).version != 4:
            raise ValueError("Delegation does not bind this exact query")
        return self

    def peer(self, selector: ContextSelector, purpose: str) -> VerifiedPanelContextPeer:
        project = str(selector.project_uuid) if selector.project_uuid else None
        if self.purpose != purpose or self.subject != selector.subject:
            raise ValueError("Delegation does not bind this exact query")
        if self.rauthy_issuer != selector.issuer or self.project_uuid != project:
            raise ValueError("Delegation does not bind this exact query")
        return VerifiedPanelContextPeer(
            "briareus:platform",
            "control-panel-api",
            selector.issuer,
            selector.subject,
            datetime.fromtimestamp(self.expires_at, UTC),
            selector.project_uuid,
        )


def decode_delegation(token: str, key: Ed25519PublicKey) -> PanelDelegationClaims:
    PanelDelegationHeader.model_validate(jwt.get_unverified_header(token))
    claims = jwt.decode(
        token,
        key,
        algorithms=["EdDSA"],
        issuer="briareus:control-panel-api",
        audience="briareus:platform",
        options={
            "require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti", "purpose", "rauthy_issuer"]
        },
    )
    return PanelDelegationClaims.model_validate(claims)
