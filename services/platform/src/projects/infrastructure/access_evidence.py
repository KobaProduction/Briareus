"""A service request's verified consumer and nonce bind every signed owner reply."""

import hashlib
from dataclasses import dataclass
from typing import Literal

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import BaseModel, ConfigDict

from runtime_peer.transport import _LIFETIME, _TYPE


@dataclass(frozen=True, slots=True)
class VerifiedAccessRequest:
    consumer: Literal["authorization", "resources"]
    nonce: str


class VerifiedNonceWire(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore", frozen=True)
    jti: str


def request_evidence(caller: str, verified_token: str) -> VerifiedAccessRequest:
    consumer: Literal["authorization", "resources"]
    if caller == "briareus:authorization":
        consumer = "authorization"
    elif caller == "briareus:resources":
        consumer = "resources"
    else:
        raise ValueError("Unexpected Platform service consumer")
    # Signature, kernel identity, body/path and replay were verified by the
    # shared PeerVerifier before entering this decoder. Decode no new authority.
    fields = VerifiedNonceWire.model_validate(
        jwt.decode(verified_token, options={"verify_signature": False})
    )
    return VerifiedAccessRequest(consumer, fields.jti)


def sign_service_response(
    key: Ed25519PrivateKey,
    binding: VerifiedAccessRequest,
    status: int,
    body: bytes,
    now: int,
) -> str:
    return jwt.encode(
        {
            "iss": "briareus:platform",
            "aud": "briareus:" + binding.consumer,
            "iat": now,
            "exp": now + _LIFETIME,
            "jti": binding.nonce,
            "status": status,
            "digest": hashlib.sha256(body).hexdigest(),
        },
        key,
        algorithm="EdDSA",
        headers={"typ": _TYPE, "kid": "briareus:platform"},
    )
