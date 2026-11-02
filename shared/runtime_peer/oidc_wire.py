"""Public issuer wire records; provider-specific trust policy stays with each owner."""

from collections.abc import Mapping
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_EXTERNAL_HEADER_KEYS = frozenset({"jku", "jwk", "x5u", "x5c"})
_PRIVATE_OR_EXTERNAL_JWK_KEYS = frozenset(
    {"jku", "x5u", "x5c", "x5t", "d", "p", "q", "dp", "dq", "qi", "oth"}
)


class IssuerWire(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)


class IssuerDiscovery(IssuerWire):
    issuer: str
    jwks_uri: str


class PublicSigningKey(IssuerWire):
    kid: str
    alg: str
    use: str | None = None
    key_ops: list[str] | None = None

    @model_validator(mode="before")
    @classmethod
    def public_material_only(cls, value: object) -> object:
        if isinstance(value, Mapping) and _PRIVATE_OR_EXTERNAL_JWK_KEYS.intersection(value):
            raise ValueError("External or private signing material is forbidden")
        return value


class RsaSigningKey(PublicSigningKey):
    kty: Literal["RSA"]
    n: str
    e: str


class EdwardsSigningKey(PublicSigningKey):
    kty: Literal["OKP"]
    crv: str
    x: str


type IssuerSigningKey = Annotated[RsaSigningKey | EdwardsSigningKey, Field(discriminator="kty")]


class IssuerSigningKeys(IssuerWire):
    keys: list[IssuerSigningKey] = Field(min_length=1, max_length=16)


class IssuerSigningHeader(IssuerWire):
    kid: str
    alg: str
    critical: bool = Field(default=False, alias="crit")

    @model_validator(mode="before")
    @classmethod
    def issuer_selected_key_only(cls, value: object) -> object:
        if isinstance(value, Mapping) and _EXTERNAL_HEADER_KEYS.intersection(value):
            raise ValueError("Header-selected external signing material is forbidden")
        return value

    @field_validator("critical", mode="before")
    @classmethod
    def critical_extensions(cls, value: object) -> bool:
        return bool(value)


class BearerBindings(IssuerWire):
    confirmation_bound: bool = Field(default=False, alias="cnf")
    delegated_actor: bool = Field(default=False, alias="act")

    @field_validator("confirmation_bound", "delegated_actor", mode="before")
    @classmethod
    def non_null_binding(cls, value: object) -> bool:
        # False and empty objects are still present claims; only null is absent.
        return value is not None
