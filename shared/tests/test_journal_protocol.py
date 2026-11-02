"""Journal signatures bind direction, scope, writer epoch and exact typed payload."""

import unittest
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from pydantic import ValidationError

from node_protocol.journal import (
    AcquireJournal,
    GetConfiguration,
    JournalRequest,
    JournalResult,
    SignedJournalReply,
    sign_reply,
    sign_request,
    verify_reply,
    verify_request,
)


class JournalProtocolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.node_uuid = uuid4()
        self.node_key = Ed25519PrivateKey.generate()
        self.core_key = Ed25519PrivateKey.generate()

    def request(self, node_uuid: UUID | None = None) -> JournalRequest:
        return JournalRequest(
            node_uuid=node_uuid or self.node_uuid,
            request_uuid=uuid4(),
            session_uuid=uuid4(),
            issued_at=100,
            expires_at=115,
            payload=AcquireJournal(),
        )

    def test_roundtrip_verifies_pinned_directional_identities(self) -> None:
        request = self.request()
        envelope = sign_request(request, self.node_key)
        self.assertEqual(
            verify_request(
                envelope,
                self.node_key.public_key(),
                node_uuid=self.node_uuid,
                now=101,
            ),
            request,
        )
        result = JournalResult(lease_epoch=1, lease_expires_at=130)
        reply = sign_reply(request, result, self.core_key, status_code=200, now=101)
        wire = SignedJournalReply.model_validate_json(reply.model_dump_json())
        self.assertEqual(
            verify_reply(wire, request, self.core_key.public_key(), now=102).result, result
        )
        with self.assertRaises(ValueError):
            verify_reply(wire, request, self.node_key.public_key(), now=102)

    def test_request_is_scoped_and_rejects_mutated_writer_or_payload(self) -> None:
        request = self.request()
        signed = sign_request(request, self.node_key)
        with self.assertRaises(ValueError):
            verify_request(signed, self.node_key.public_key(), node_uuid=uuid4(), now=101)
        replacement = JournalRequest(
            node_uuid=self.node_uuid,
            request_uuid=request.request_uuid,
            session_uuid=uuid4(),
            issued_at=100,
            expires_at=115,
            payload=GetConfiguration(),
            lease_epoch=1,
        )
        mutated = signed.model_copy(update={"request": replacement})
        with self.assertRaises(ValueError):
            verify_request(mutated, self.node_key.public_key(), node_uuid=self.node_uuid, now=101)

    def test_reply_cannot_be_replayed_for_other_request_or_modified_result(self) -> None:
        request = self.request()
        reply = sign_reply(
            request, JournalResult(lease_epoch=1), self.core_key, status_code=200, now=101
        )
        with self.assertRaises(ValueError):
            verify_reply(reply, self.request(), self.core_key.public_key(), now=102)
        modified = reply.reply.model_copy(update={"result": JournalResult(lease_epoch=2)})
        with self.assertRaises(ValueError):
            verify_reply(
                reply.model_copy(update={"reply": modified}),
                request,
                self.core_key.public_key(),
                now=102,
            )

    def test_expiry_and_future_proofs_fail_closed(self) -> None:
        request = self.request()
        signed = sign_request(request, self.node_key)
        for now in (94, 115, 120):
            with self.assertRaises(ValueError):
                verify_request(
                    signed, self.node_key.public_key(), node_uuid=self.node_uuid, now=now
                )
        reply = sign_reply(request, JournalResult(), self.core_key, status_code=200, now=101)
        with self.assertRaises(ValueError):
            verify_reply(reply, request, self.core_key.public_key(), now=116)

    def test_epoch_and_payload_shapes_are_not_optional_bags(self) -> None:
        request = self.request()
        with self.assertRaises(ValidationError):
            JournalRequest.model_validate_json(
                request.model_dump_json().replace('"action":"acquire"', '"action":"configuration"')
            )
        with self.assertRaises(ValidationError):
            JournalRequest(
                node_uuid=self.node_uuid,
                request_uuid=uuid4(),
                session_uuid=uuid4(),
                issued_at=100,
                expires_at=116,
                payload=AcquireJournal(),
            )


if __name__ == "__main__":
    unittest.main()
