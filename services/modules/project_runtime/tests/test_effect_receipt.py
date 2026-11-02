"""A receipt cannot substitute command identity, result, or cleanup certainty."""

import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from modules.project_runtime.domain.effect_receipt import (
    OwnerEffectUnavailable,
    ReceiptExpectation,
)
from modules.project_runtime.infrastructure.effect_receipt import (
    command_binding,
    receipt_observation,
    verify_attestation,
)
from modules.project_runtime.owner_authorization import VerifiedOwnerRecipient
from modules.project_runtime.owner_effects import (
    OwnerEffectCommand,
    OwnerEffectReceipt,
    OwnerFenceDTO,
    SignedOwnerEffectReceipt,
)


def command() -> OwnerEffectCommand:
    operation_uuid = uuid4()
    return OwnerEffectCommand(
        owner="files",
        owner_database="briareus_files",
        phase="reserve",
        action="files.write",
        operation_uuid=operation_uuid,
        idempotency_uuid=operation_uuid,
        project_id=uuid4(),
        agent_session_uuid=uuid4(),
        actor_id=uuid4(),
        recipient_service_id=uuid4(),
        recipient_instance_uuid=uuid4(),
        request_sha256="a" * 64,
        target_sha256="b" * 64,
        payload_sha256="c" * 64,
        payload_type="FilesReserve",
        expected_version=2,
        fence=OwnerFenceDTO(
            identity_version=1,
            identity_revocation_epoch=0,
            identity_authority_epoch=uuid4(),
            control_state_version=1,
            control_revision="d" * 64,
            control_scope_epoch=0,
            control_authority_epoch=uuid4(),
            access_session_version=1,
            access_revocation_epoch=0,
            access_authority_epoch=uuid4(),
        ),
    )


def receipt(effect: OwnerEffectCommand, now: datetime) -> OwnerEffectReceipt:
    return OwnerEffectReceipt(
        owner=effect.owner,
        owner_database=effect.owner_database,
        phase=effect.phase,
        action=effect.action,
        operation_uuid=effect.operation_uuid,
        idempotency_uuid=effect.operation_uuid,
        project_id=effect.project_id,
        agent_session_uuid=effect.agent_session_uuid,
        actor_id=effect.actor_id,
        recipient_service_id=effect.recipient_service_id,
        recipient_instance_uuid=effect.recipient_instance_uuid,
        request_sha256=effect.request_sha256,
        target_sha256=effect.target_sha256,
        payload_sha256=effect.payload_sha256,
        result_sha256="e" * 64,
        fence=effect.fence,
        owner_revision=2,
        state="reserved",
        expires_at=now + timedelta(seconds=5),
        acknowledged_at=now,
    )


class EffectReceiptTests(unittest.TestCase):
    def test_signed_token_and_receipt_bind_the_original_command(self) -> None:
        effect, now = command(), datetime.now(UTC)
        outcome = receipt(effect, now)
        key = Ed25519PrivateKey.generate()
        public = key.public_key()
        kid = hashlib.sha256(
            public.public_bytes(
                serialization.Encoding.Raw,
                serialization.PublicFormat.Raw,
            )
        ).hexdigest()
        token = jwt.encode(
            {
                "iss": "briareus-files",
                "aud": f"owner-effect:{effect.recipient_service_id}",
                "iat": int(now.timestamp()),
                "nbf": int(now.timestamp()),
                "exp": int(now.timestamp()) + 10,
                "jti": str(uuid4()),
                "purpose": "owner-effect-receipt-v1",
                "receipt": outcome.model_dump(mode="json"),
            },
            key,
            algorithm="EdDSA",
            headers={"typ": "briareus-owner-effect+jwt", "kid": kid},
        )
        peer = VerifiedOwnerRecipient(
            effect.recipient_service_id,
            effect.recipient_instance_uuid,
            now + timedelta(seconds=10),
            "mtls",
        )
        signed = SignedOwnerEffectReceipt(receipt=outcome, attestation_jws=token)
        verified = verify_attestation(
            signed,
            key=public,
            owner="files",
            recipient=peer,
        )
        expectation = ReceiptExpectation(
            command_binding(effect),
            "e" * 64,
            2,
            peer.expires_at,
            verified.expires_at,
            now,
        )
        observation = receipt_observation(verified.receipt)
        observation.require_for(expectation)
        forged = replace(observation, binding=replace(observation.binding, operation_uuid=uuid4()))
        with self.assertRaises(OwnerEffectUnavailable) as raised:
            forged.require_for(expectation)
        self.assertTrue(raised.exception.outcome_unknown)
        self.assertEqual(raised.exception.code, "OWNER_EFFECT_SIGNED_REPLY_INVALID")
        with self.assertRaises(OwnerEffectUnavailable):
            verify_attestation(
                signed,
                key=Ed25519PrivateKey.generate().public_key(),
                owner="files",
                recipient=peer,
            )

    def test_unknown_is_inspect_only_and_revision_and_result_are_bound(self) -> None:
        effect, now = command(), datetime.now(UTC)
        observation = receipt_observation(receipt(effect, now))
        expected = ReceiptExpectation(
            command_binding(effect),
            "e" * 64,
            2,
            now + timedelta(seconds=8),
            now + timedelta(seconds=10),
            now,
        )
        for changed in (
            replace(observation, result_sha256="f" * 64),
            replace(observation, owner_revision=1),
            replace(observation, expires_at=now),
            replace(observation, expires_at=now + timedelta(seconds=9)),
        ):
            with self.subTest(changed=changed), self.assertRaises(OwnerEffectUnavailable):
                changed.require_for(expected)
        with self.assertRaises(OwnerEffectUnavailable) as raised:
            replace(observation, state="unknown").require_for(expected)
        self.assertEqual(raised.exception.code, "OWNER_EFFECT_REQUIRES_INSPECT")
        inspect_binding = replace(observation.binding, phase="inspect")
        replace(observation, binding=inspect_binding, state="unknown").require_for(
            replace(expected, binding=inspect_binding),
        )
