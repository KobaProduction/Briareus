"""Public-key publication and display context for the retained OAuth adapter."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel


class PublicEcJwk(BaseModel):
    kty: Literal["EC"] = "EC"
    use: Literal["sig"] = "sig"
    alg: Literal["ES256"] = "ES256"
    kid: str
    crv: Literal["P-256"] = "P-256"
    x: str
    y: str


class PublicJwkSet(BaseModel):
    keys: list[PublicEcJwk]


@dataclass(frozen=True, slots=True)
class OAuthLoginContext:
    client_name: str
    resource: str
