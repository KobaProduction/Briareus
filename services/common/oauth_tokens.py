from __future__ import annotations

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pydantic import ValidationError

from .oauth_token_contracts import OAuthAccessClaims


def load_oauth_public_key(pem: str) -> ec.EllipticCurvePublicKey:
    key = serialization.load_pem_public_key(pem.encode())
    if not isinstance(key, ec.EllipticCurvePublicKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("AUTHORIZATION_JWT_PUBLIC_KEY_PEM must contain a P-256 EC public key")
    return key


def verify_oauth_access_token(
    token: str,
    *,
    public_key: ec.EllipticCurvePublicKey,
    issuer: str,
    audience: str,
) -> OAuthAccessClaims | None:
    try:
        payload = jwt.decode(
            token,
            public_key,
            algorithms=["ES256"],
            issuer=issuer,
            audience=audience,
            options={"require": ["iss", "aud", "sub", "client_id", "exp", "iat", "jti"]},
        )
        return OAuthAccessClaims.model_validate(payload)
    except (jwt.PyJWTError, ValidationError):
        return None
