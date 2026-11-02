"""Pinned ledger receipts cannot authorize takeover without confirmed cleanup."""

import hashlib
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from modules.project_runtime.a9_signed_lease import (
    A9SignedLeaseUntrusted,
    RuntimeLeaseReceipt,
    SignedRuntimeLeaseReceipt,
    verify_a9_signed_lease,
)
from modules.project_runtime.authorization import ProjectPermit


@dataclass(frozen=True, slots=True)
class LeaseFixture:
    permit: ProjectPermit
    runtime_uuid: UUID
    service_uuid: UUID
    instance_uuid: UUID
    key: Ed25519PrivateKey
    now: datetime

    def lease(self) -> RuntimeLeaseReceipt:
        return RuntimeLeaseReceipt(
            runtime_session_uuid=self.runtime_uuid,
            project_id=self.permit.project_id,
            agent_session_uuid=self.permit.session_uuid,
            actor_user_id=self.permit.actor_id,
            owner_service_id=self.service_uuid,
            owner_instance_uuid=self.instance_uuid,
            lease_nonce=uuid4(),
            kind="terminal",
            state="active",
            revision=1,
            idle_expires_at=self.now + timedelta(seconds=20),
            hard_expires_at=self.now + timedelta(seconds=30),
            lease_expires_at=self.now + timedelta(seconds=20),
            cleanup_state="not_needed",
        )

    def sign(self, lease: RuntimeLeaseReceipt) -> SignedRuntimeLeaseReceipt:
        expires_at = datetime.fromtimestamp(int(self.now.timestamp()) + 10, UTC)
        public = self.key.public_key().public_bytes(
            serialization.Encoding.Raw,
            serialization.PublicFormat.Raw,
        )
        token = jwt.encode(
            {
                "iss": "briareus-authorization",
                "aud": "runtime-lease:terminal",
                "purpose": "runtime-ledger-attestation-v1",
                "jti": str(uuid4()),
                "iat": int(self.now.timestamp()),
                "nbf": int(self.now.timestamp()),
                "exp": int(expires_at.timestamp()),
                "recipient_service_id": str(self.service_uuid),
                "recipient_instance_uuid": str(self.instance_uuid),
                "project_access_revision": self.permit.project_access_revision,
                "agent_session_version": self.permit.decision_version,
                "lease": lease.model_dump(mode="json"),
            },
            self.key,
            algorithm="EdDSA",
            headers={
                "typ": "briareus-runtime-lease+jwt",
                "kid": hashlib.sha256(public).hexdigest(),
            },
        )
        return SignedRuntimeLeaseReceipt(
            lease=lease,
            attestation_jws=token,
            attestation_expires_at=expires_at,
        )

    def verify(self, signed: SignedRuntimeLeaseReceipt) -> RuntimeLeaseReceipt:
        return verify_a9_signed_lease(
            signed,
            trusted_public_key=self.key.public_key(),
            expected_service_id=self.service_uuid,
            expected_instance_uuid=self.instance_uuid,
            expected_audience="terminal",
            permit=self.permit,
            expected_runtime_session_uuid=self.runtime_uuid,
            expected_kind="terminal",
        )


def fixture() -> LeaseFixture:
    now = datetime.now(UTC)
    permit = ProjectPermit(
        uuid4(),
        uuid4(),
        uuid4(),
        "terminal.attach",
        now + timedelta(seconds=30),
        1,
        "a" * 64,
    )
    return LeaseFixture(permit, uuid4(), uuid4(), uuid4(), Ed25519PrivateKey.generate(), now)


class RuntimeLeaseTests(unittest.TestCase):
    def test_pinned_token_matches_snapshot_and_original_scope(self) -> None:
        case = fixture()
        lease = case.lease()
        signed = case.sign(lease)
        self.assertEqual(case.verify(signed), lease)
        changed = signed.model_copy(update={"lease": lease.model_copy(update={"revision": 2})})
        with self.assertRaises(A9SignedLeaseUntrusted) as raised:
            case.verify(changed)
        self.assertEqual(raised.exception.code, "A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
        forged = lease.model_copy(update={"runtime_session_uuid": uuid4()})
        with self.assertRaises(A9SignedLeaseUntrusted):
            case.verify(case.sign(forged))

    def test_takeover_requires_terminal_state_and_confirmed_cleanup(self) -> None:
        case = fixture()
        old_instance = case.lease().model_copy(update={"owner_instance_uuid": uuid4()})
        for invalid in (
            old_instance,
            old_instance.model_copy(update={"state": "closed", "cleanup_state": "pending"}),
        ):
            with self.subTest(invalid=invalid), self.assertRaises(A9SignedLeaseUntrusted) as raised:
                case.verify(case.sign(invalid))
            self.assertEqual(raised.exception.code, "A9_LEASE_TAKEOVER_WITHOUT_OS_CLEANUP")
        cleaned = old_instance.model_copy(update={"state": "closed", "cleanup_state": "confirmed"})
        self.assertEqual(case.verify(case.sign(cleaned)), cleaned)

    def test_active_token_cannot_outlive_lease(self) -> None:
        case = fixture()
        expired = case.lease().model_copy(
            update={"lease_expires_at": case.now + timedelta(seconds=2)}
        )
        with self.assertRaises(A9SignedLeaseUntrusted) as raised:
            case.verify(case.sign(expired))
        self.assertEqual(raised.exception.code, "A9_LEASE_SIGNED_SQL_SNAPSHOT_MISMATCH")
