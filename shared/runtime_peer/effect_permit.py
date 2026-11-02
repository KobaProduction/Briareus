"""The existing private effect JWT wire contract, shared by signer and resource codecs."""

from typing import Literal
from uuid import UUID

import jwt
from pydantic import (
    UUID4,
    BaseModel,
    ConfigDict,
    StrictFloat,
    StrictInt,
    StrictStr,
    field_validator,
)

from .domain.private_effect import PrivateEffectFacts
from .transport import PeerIdentity


class PrivateEffectClaims(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, strict=True)
    iss: Literal["briareus:authorization"] = "briareus:authorization"
    aud: StrictStr
    iat: StrictInt
    nbf: StrictInt | StrictFloat
    exp: StrictInt
    jti: UUID4
    project_uuid: UUID4
    actor_uuid: UUID4
    session_uuid: UUID4
    operation_uuid: UUID4
    grant_revision: StrictInt
    tool: StrictStr
    arguments_digest: StrictStr
    resource_id: StrictStr
    resource_revision: StrictInt | StrictFloat

    @field_validator(
        "jti", "project_uuid", "actor_uuid", "session_uuid", "operation_uuid", mode="before"
    )
    @classmethod
    def canonical_identity(cls, value: object) -> UUID:
        if isinstance(value, UUID):
            return value
        if not isinstance(value, str):
            raise ValueError("Canonical effect identity required")
        identity = UUID(value)
        if str(identity) != value:
            raise ValueError("Canonical effect identity required")
        return identity

    def facts(self) -> PrivateEffectFacts:
        return PrivateEffectFacts(
            token_uuid=self.jti,
            actor_uuid=self.actor_uuid,
            session_uuid=self.session_uuid,
            operation_uuid=self.operation_uuid,
            issued_at=self.iat,
            not_before=self.nbf,
            expires_at=self.exp,
            project_uuid=self.project_uuid,
            resource_id=self.resource_id,
            resource_revision=self.resource_revision,
            tool=self.tool,
            arguments_digest=self.arguments_digest,
            grant_revision=self.grant_revision,
        )


def decode_effect_permit(token: str, authority: PeerIdentity, audience: str) -> PrivateEffectFacts:
    header = jwt.get_unverified_header(token)
    if header.get("typ") != "briareus-effect-permit+jwt" or header.get("crit"):
        raise ValueError("A real private effect decision is required")
    claims = jwt.decode(
        token,
        authority.public_key,
        algorithms=["EdDSA"],
        issuer="briareus:authorization",
        audience=audience,
        options={"require": list(PrivateEffectClaims.model_fields)},
    )
    return PrivateEffectClaims.model_validate(claims).facts()
