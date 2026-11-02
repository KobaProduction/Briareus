from __future__ import annotations

import base64
import hashlib as hashlib
import json
import secrets as secrets
import time

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id as Argon2id

from common.credential_primitives import _ARGON2_ITERATIONS as _ARGON2_ITERATIONS
from common.credential_primitives import _ARGON2_LANES as _ARGON2_LANES
from common.credential_primitives import _ARGON2_LENGTH as _ARGON2_LENGTH
from common.credential_primitives import _ARGON2_MEMORY_KIB as _ARGON2_MEMORY_KIB
from common.credential_primitives import hash_password as hash_password
from common.credential_primitives import random_token as random_token
from common.credential_primitives import token_hash as token_hash
from common.credential_primitives import verify_password as verify_password
from common.oauth_token_contracts import OAuthAccessClaims
from common.oauth_tokens import load_oauth_public_key as _load_oauth_public_key
from common.oauth_tokens import verify_oauth_access_token

from .application.token_views import PublicEcJwk

load_public_key = _load_oauth_public_key


def load_private_key(pem: str) -> ec.EllipticCurvePrivateKey:
    key = serialization.load_pem_private_key(pem.encode(), password=None)
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError("AUTHORIZATION_JWT_PRIVATE_KEY_PEM must contain a P-256 EC private key")
    return key


def public_jwk(public_key: ec.EllipticCurvePublicKey, *, kid: str) -> PublicEcJwk:
    numbers = public_key.public_numbers()

    def encoded(value: int) -> str:
        raw = value.to_bytes(32, "big")
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")

    return PublicEcJwk(
        kty="EC",
        use="sig",
        alg="ES256",
        kid=kid,
        crv="P-256",
        x=encoded(numbers.x),
        y=encoded(numbers.y),
    )


def issue_access_token(
    *,
    private_key: ec.EllipticCurvePrivateKey,
    kid: str,
    issuer: str,
    audience: str,
    subject: str,
    username: str,
    client_id: str,
    scopes: list[str],
    session_id: str,
    ttl_seconds: int,
) -> tuple[str, int]:
    now = int(time.time())
    expires_at = now + ttl_seconds
    payload = OAuthAccessClaims(
        iss=issuer,
        aud=audience,
        sub=subject,
        username=username,
        client_id=client_id,
        scope=" ".join(scopes),
        session_id=session_id,
        jti=random_token(18),
        iat=now,
        exp=expires_at,
    )
    token = jwt.encode(
        payload.model_dump(mode="json", exclude_unset=True),
        private_key,
        algorithm="ES256",
        headers={"kid": kid, "typ": "JWT"},
    )
    return token, expires_at


def verify_access_token(
    token: str,
    *,
    public_key: ec.EllipticCurvePublicKey,
    issuer: str,
    audience: str,
) -> OAuthAccessClaims | None:
    return verify_oauth_access_token(token, public_key=public_key, issuer=issuer, audience=audience)


def json_dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
