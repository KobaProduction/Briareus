"""Pinned Ed25519 verification and adaptation of the legacy receipt ABI."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from pydantic import UUID4, BaseModel, ConfigDict, StrictInt

from project_runtime_client.domain.effect_receipt import (
    EffectReceiptBinding,
    OwnerEffectUnavailable,
    ReceiptObservation,
    RevocationFence,
)
from project_runtime_client.owner_authorization import VerifiedOwnerRecipient

from .effect_contracts import OwnerEffectReceipt, OwnerFenceDTO, SignedOwnerEffectReceipt

if TYPE_CHECKING:
    from project_runtime_client.owner_effects import (
        OwnerEffectCommand,
    )


class ReceiptClaims(BaseModel):
    """The SDK's raw JWT payload is consumed only at this boundary."""

    model_config = ConfigDict(strict=True, frozen=True, extra="ignore")
    jti: UUID4
    purpose: Literal["owner-effect-receipt-v1"]
    exp: StrictInt
    iat: StrictInt
    receipt: OwnerEffectReceipt


@dataclass(frozen=True, slots=True)
class VerifiedEffectAttestation:
    receipt: OwnerEffectReceipt
    expires_at: datetime


def verify_attestation(
    attestation: SignedOwnerEffectReceipt,
    *,
    key: Ed25519PublicKey,
    owner: str,
    recipient: VerifiedOwnerRecipient,
) -> VerifiedEffectAttestation:
    header = jwt.get_unverified_header(attestation.attestation_jws)
    key_digest = hashlib.sha256(
        key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
    ).hexdigest()
    if (
        header.get("alg") != "EdDSA"
        or header.get("typ") != "briareus-owner-effect+jwt"
        or header.get("kid") != key_digest
        or header.get("crit")
    ):
        raise OwnerEffectUnavailable("OWNER_EFFECT_SIGNER_INVALID", unknown=True)
    raw_claims = jwt.decode(
        attestation.attestation_jws,
        key,
        algorithms=["EdDSA"],
        audience=f"owner-effect:{recipient.service_id}",
        issuer=f"briareus-{owner}",
        leeway=0,
        options={"require": ["iss", "aud", "iat", "nbf", "exp", "jti", "purpose", "receipt"]},
    )
    if (
        type(raw_claims["exp"]) is not int
        or type(raw_claims["iat"]) is not int
        or raw_claims["purpose"] != "owner-effect-receipt-v1"
    ):
        raise OwnerEffectUnavailable("OWNER_EFFECT_SIGNED_REPLY_INVALID", unknown=True)
    claims = ReceiptClaims.model_validate_json(json.dumps(raw_claims))
    signed = claims.receipt
    if not 0 < claims.exp - claims.iat <= 30 or signed != attestation.receipt:
        raise OwnerEffectUnavailable("OWNER_EFFECT_SIGNED_REPLY_INVALID", unknown=True)
    return VerifiedEffectAttestation(signed, datetime.fromtimestamp(claims.exp, UTC))


def _fence(fence: OwnerFenceDTO) -> RevocationFence:
    return RevocationFence(
        fence.identity_version,
        fence.identity_revocation_epoch,
        fence.identity_authority_epoch,
        fence.control_state_version,
        fence.control_revision,
        fence.control_scope_epoch,
        fence.control_authority_epoch,
        fence.access_session_version,
        fence.access_revocation_epoch,
        fence.access_authority_epoch,
    )


def command_binding(command: OwnerEffectCommand) -> EffectReceiptBinding:
    return EffectReceiptBinding(
        command.owner,
        command.owner_database,
        command.project_id,
        command.actor_id,
        command.agent_session_uuid,
        command.operation_uuid,
        command.recipient_service_id,
        command.recipient_instance_uuid,
        command.phase,
        command.action,
        command.request_sha256,
        command.target_sha256,
        command.payload_sha256,
        _fence(command.fence),
    )


def receipt_observation(receipt: OwnerEffectReceipt) -> ReceiptObservation:
    return ReceiptObservation(
        binding=EffectReceiptBinding(
            receipt.owner,
            receipt.owner_database,
            receipt.project_id,
            receipt.actor_id,
            receipt.agent_session_uuid,
            receipt.operation_uuid,
            receipt.recipient_service_id,
            receipt.recipient_instance_uuid,
            receipt.phase,
            receipt.action,
            receipt.request_sha256,
            receipt.target_sha256,
            receipt.payload_sha256,
            _fence(receipt.fence),
        ),
        result_sha256=receipt.result_sha256,
        owner_revision=receipt.owner_revision,
        expires_at=receipt.expires_at,
        state=receipt.state,
    )
