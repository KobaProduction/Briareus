"""Pinned Runtime lease token codec; SDK dictionaries terminate at this adapter."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from uuid import UUID

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import UUID4, BaseModel, ConfigDict, StrictInt, ValidationError, field_validator

from project_runtime_client.domain.runtime_lease import (
    A9SignedLeaseUntrusted,
    RuntimeLeaseClaims,
    RuntimeLeaseExpectation,
    RuntimeLeaseLifetime,
    RuntimeLeaseScope,
    RuntimeLeaseSnapshot,
)

from .lease_contracts import RuntimeLeaseReceipt, SignedRuntimeLeaseReceipt


class RuntimeLeaseClaimPayload(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True, extra="ignore")
    jti: UUID4
    purpose: str
    recipient_service_id: UUID4
    recipient_instance_uuid: UUID4
    project_access_revision: str
    agent_session_version: StrictInt
    iat: StrictInt
    nbf: StrictInt
    exp: StrictInt
    lease: RuntimeLeaseReceipt

    @field_validator("recipient_service_id", "recipient_instance_uuid", mode="before")
    @classmethod
    def canonical_recipient(cls, value: object) -> UUID:
        if isinstance(value, str):
            parsed = UUID(value)
            if str(parsed) == value:
                return parsed
        raise ValueError("Canonical lease recipient UUID required")


@dataclass(frozen=True, slots=True)
class VerifiedRuntimeLease:
    receipt: RuntimeLeaseReceipt
    claims: RuntimeLeaseClaims


def verify_runtime_lease_token(
    response: SignedRuntimeLeaseReceipt,
    *,
    key: Ed25519PublicKey,
    expected: RuntimeLeaseExpectation,
) -> VerifiedRuntimeLease:
    header = jwt.get_unverified_header(response.attestation_jws)
    key_digest = hashlib.sha256(
        key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    if (
        header.get("alg") != "EdDSA"
        or header.get("typ") != "briareus-runtime-lease+jwt"
        or header.get("kid") != key_digest
        or header.get("crit")
    ):
        raise A9SignedLeaseUntrusted("A9_LEASE_KEY_OR_HEADER_UNTRUSTED")
    raw = jwt.decode(
        response.attestation_jws,
        key,
        algorithms=["EdDSA"],
        audience=f"runtime-lease:{expected.audience}",
        issuer="briareus-authorization",
        options={
            "require": [
                "iss",
                "aud",
                "purpose",
                "jti",
                "iat",
                "nbf",
                "exp",
                "recipient_service_id",
                "recipient_instance_uuid",
                "project_access_revision",
                "agent_session_version",
                "lease",
            ]
        },
        leeway=0,
    )
    try:
        claims = RuntimeLeaseClaimPayload.model_validate_json(json.dumps(raw))
    except ValidationError as exc:
        raise A9SignedLeaseUntrusted("A9_LEASE_CLAIMS_SCOPE_MISMATCH") from exc
    facts = RuntimeLeaseClaims(
        claims.jti,
        claims.purpose,
        claims.recipient_service_id,
        claims.recipient_instance_uuid,
        claims.project_access_revision,
        claims.agent_session_version,
        claims.iat,
        claims.nbf,
        claims.exp,
    )
    facts.require_for(expected)
    signed = claims.lease
    if signed != response.lease:
        raise A9SignedLeaseUntrusted("A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
    return VerifiedRuntimeLease(signed, facts)


def runtime_lease_snapshot(receipt: RuntimeLeaseReceipt) -> RuntimeLeaseSnapshot:
    return RuntimeLeaseSnapshot(
        scope=RuntimeLeaseScope(
            receipt.project_id,
            receipt.agent_session_uuid,
            receipt.actor_user_id,
            receipt.owner_service_id,
            receipt.runtime_session_uuid,
            receipt.kind,
        ),
        owner_instance_uuid=receipt.owner_instance_uuid,
        nonce=receipt.lease_nonce,
        state=receipt.state,
        cleanup=receipt.cleanup_state,
        lifetime=RuntimeLeaseLifetime(
            receipt.idle_expires_at,
            receipt.hard_expires_at,
            receipt.lease_expires_at,
        ),
    )
