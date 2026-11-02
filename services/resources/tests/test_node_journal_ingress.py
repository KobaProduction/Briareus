"""Purpose-bound gRPC service results disclose only fixed, signed journal outcomes."""

import time
import unittest
from dataclasses import dataclass
from uuid import uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from projects.domain.execution_journal import JournalConflict, JournalRejected
from projects.node_journal_ingress import JournalService, JournalServiceProvider

from node_protocol.journal import (
    AcquireJournal,
    JournalRequest,
    JournalResult,
    SignedJournalRequest,
    sign_request,
    verify_reply,
)


@dataclass
class StubService:
    result: JournalResult
    failure: Exception | None = None

    async def execute(self, envelope: SignedJournalRequest, *, now: int) -> JournalResult:
        if self.failure is not None:
            raise self.failure
        if now <= 0 or envelope.request.expires_at <= now:
            raise ValueError("Invalid test clock")
        return self.result


class StubProvider(JournalServiceProvider):
    def __init__(self, key: Ed25519PrivateKey, service: JournalService | None) -> None:
        super().__init__(key, None)
        self.service = service

    def resolve(self) -> JournalService | None:
        return self.service


class JournalIngressTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.core_key = Ed25519PrivateKey.generate()
        now = int(time.time())
        self.request = JournalRequest(
            node_uuid=uuid4(),
            request_uuid=uuid4(),
            session_uuid=uuid4(),
            issued_at=now,
            expires_at=now + 15,
            payload=AcquireJournal(),
        )
        self.envelope = sign_request(self.request, Ed25519PrivateKey.generate())

    async def test_success_preserves_typed_result_and_exact_request_binding(self) -> None:
        result = JournalResult(lease_epoch=1, lease_expires_at=int(time.time()) + 30)
        provider = StubProvider(self.core_key, StubService(result))
        signed = await provider.execute(self.envelope)
        verified = verify_reply(
            signed, self.request, self.core_key.public_key(), now=int(time.time())
        )
        self.assertEqual(verified.status_code, 200)
        self.assertEqual(verified.result, result)

    async def test_missing_database_fails_closed_without_an_alternate_backend(self) -> None:
        signed = await StubProvider(self.core_key, None).execute(self.envelope)
        verified = verify_reply(
            signed, self.request, self.core_key.public_key(), now=int(time.time())
        )
        self.assertEqual(verified.status_code, 503)
        self.assertEqual(verified.result, JournalResult(error="JOURNAL_UNAVAILABLE"))

    async def test_errors_are_fixed_signed_outcomes_without_underlying_diagnostics(self) -> None:
        for failure, status, code in (
            (JournalRejected("private rejected details"), 403, "JOURNAL_REJECTED"),
            (JournalConflict("private receipt details"), 409, "JOURNAL_CONFLICT"),
            (RuntimeError("private database details"), 503, "JOURNAL_UNAVAILABLE"),
        ):
            provider = StubProvider(self.core_key, StubService(JournalResult(), failure))
            signed = await provider.execute(self.envelope)
            verified = verify_reply(
                signed, self.request, self.core_key.public_key(), now=int(time.time())
            )
            self.assertEqual(verified.status_code, status)
            self.assertEqual(verified.result.error, code)
            self.assertNotIn("private", signed.model_dump_json())


if __name__ == "__main__":
    unittest.main()
