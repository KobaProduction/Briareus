"""Owner-private Ed25519 service/delegation JWT boundary; no persistence or grants."""

from typing import Literal
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from common.platform_errors import AuthenticationRequired

AUTHORIZATION_AUDIENCE = "platform-authorization"
DELEGATION_ISSUER = "briareus-authorization"

type RuntimeTokenPurpose = Literal["platform-service+jwt", "platform-delegation+jwt"]


class RuntimeOperationClaims(BaseModel):
    model_config = ConfigDict(extra="forbid")

    iss: str
    aud: str
    jti: UUID
    service_id: UUID
    instance_uuid: UUID
    project_id: UUID
    session_uuid: UUID
    operation: str
    resource_id: UUID | None
    request_fingerprint: str
    purpose: str
    iat: int
    nbf: int
    exp: int


class ServiceAssertionClaims(RuntimeOperationClaims):
    key_version: int = Field(ge=1)
    target_audience: str
    delegation_jti: UUID
    correlation_id: UUID


class DelegationClaims(RuntimeOperationClaims):
    actor_id: UUID
    actor_credential_version: int = Field(ge=1)
    actor_admin_jti_digest: str
    decision_version: str
    session_version: int = Field(ge=1)


class _RuntimeTokenHeader(BaseModel):
    model_config = ConfigDict(extra="ignore")

    alg: Literal["EdDSA"]
    typ: RuntimeTokenPurpose
    kid: str | None = None


def _header(token: str, purpose: RuntimeTokenPurpose) -> _RuntimeTokenHeader:
    if not 64 <= len(token) <= 8192:
        raise AuthenticationRequired("service assertion is malformed")
    try:
        raw = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise AuthenticationRequired("invalid signed service assertion") from exc
    # Inspect critical-extension metadata only inside the untrusted JOSE adapter.
    if raw.get("alg") != "EdDSA" or raw.get("typ") != purpose or raw.get("crit"):
        raise AuthenticationRequired("service assertion header rejected")
    try:
        return _RuntimeTokenHeader.model_validate(raw)
    except ValidationError as exc:
        raise AuthenticationRequired("service assertion header rejected") from exc


def service_key_id(token: str) -> UUID:
    header = _header(token, "platform-service+jwt")
    try:
        key_id = UUID(header.kid) if header.kid is not None else None
        if key_id is None or key_id.version != 4:
            raise ValueError("not a UUIDv4 key")
    except (ValueError, TypeError) as exc:
        raise AuthenticationRequired("unregistered service key identity") from exc
    return key_id


def _decode[T: RuntimeOperationClaims](
    token: str,
    public_key: Ed25519PublicKey,
    claims: type[T],
    *,
    issuer: str,
    audience: str,
    error: str,
) -> T:
    try:
        raw = jwt.decode(
            token,
            public_key,
            algorithms=["EdDSA"],
            issuer=issuer,
            audience=audience,
            options={"require": list(claims.model_fields)},
            leeway=0,
        )
        return claims.model_validate(raw)
    except (jwt.PyJWTError, ValidationError, ValueError, TypeError) as exc:
        raise AuthenticationRequired(error) from exc


def decode_service_assertion(
    token: str, public_key: Ed25519PublicKey, service_id: UUID
) -> ServiceAssertionClaims:
    return _decode(
        token,
        public_key,
        ServiceAssertionClaims,
        issuer=f"service:{service_id}",
        audience=AUTHORIZATION_AUDIENCE,
        error="runtime service assertion invalid",
    )


def decode_delegation(
    token: str, public_key: Ed25519PublicKey, *, audience: str
) -> DelegationClaims:
    _header(token, "platform-delegation+jwt")
    return _decode(
        token,
        public_key,
        DelegationClaims,
        issuer=DELEGATION_ISSUER,
        audience=audience,
        error="backend actor delegation invalid",
    )


def sign_service_assertion(
    claims: ServiceAssertionClaims, private_key: Ed25519PrivateKey, *, key_id: UUID
) -> str:
    return jwt.encode(
        claims.model_dump(mode="json"),
        private_key,
        algorithm="EdDSA",
        headers={"typ": "platform-service+jwt", "kid": str(key_id)},
    )


def sign_delegation(claims: DelegationClaims, private_key: Ed25519PrivateKey) -> str:
    return jwt.encode(
        claims.model_dump(mode="json"),
        private_key,
        algorithm="EdDSA",
        headers={"typ": "platform-delegation+jwt", "kid": "platform"},
    )
