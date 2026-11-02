"""Outcome diagnostics cannot replay effects or turn transport loss into success."""

import asyncio
import unittest

from bridge._call_journal import outcome
from bridge.application.call_outcome import RecordCallOutcome
from bridge.domain.call_outcome import CallObservation, CallOutcome, ReplyFacts


class Authority:
    def __init__(self, failure: Exception | None = None) -> None:
        self.calls: list[tuple[str, CallOutcome, int]] = []
        self.failure = failure

    async def record_call(self, *, permit: str, status: CallOutcome, duration_ms: int) -> None:
        self.calls.append((permit, status, duration_ms))
        if self.failure is not None:
            raise self.failure


class CallOutcomeTests(unittest.IsolatedAsyncioTestCase):
    def test_complete_sse_requires_every_data_frame_to_be_valid(self) -> None:
        valid = b'data: {"result":{}}\n\n'
        self.assertEqual(outcome(200, valid, True), "completed")
        self.assertEqual(outcome(200, b"data: malformed\n\n" + valid, True), "unknown")
        self.assertEqual(outcome(200, b'{"error":{"code":-1}}', True), "failed")
        self.assertEqual(outcome(403, b"malformed", False), "failed")

    async def test_records_only_bounded_outcome_and_duration(self) -> None:
        authority = Authority()
        use_case = RecordCallOutcome(authority, clock=lambda: 12.0)
        observation = CallObservation(200, True, ReplyFacts(True, False, False))
        await use_case.execute("signed-permit", observation, 10.0)
        self.assertEqual(authority.calls, [("signed-permit", "completed", 2000)])

    async def test_delivery_failure_never_retries_or_propagates(self) -> None:
        authority = Authority(ValueError("fixture owner unavailable"))
        use_case = RecordCallOutcome(authority, clock=lambda: 100000.0)
        with self.assertLogs("bridge.application.call_outcome", level="WARNING"):
            await use_case.execute("signed-permit", CallObservation(200, False, None), 0.0)
        self.assertEqual(authority.calls, [("signed-permit", "unknown", 86400000)])

    async def test_cancellation_propagates_without_another_delivery(self) -> None:
        class CancelledAuthority:
            async def record_call(
                self, *, permit: str, status: CallOutcome, duration_ms: int
            ) -> None:
                del permit, status, duration_ms
                raise asyncio.CancelledError

        with self.assertRaises(asyncio.CancelledError):
            await RecordCallOutcome(CancelledAuthority(), clock=lambda: 1.0).execute(
                "signed-permit",
                CallObservation(200, True, ReplyFacts(True, False, True)),
                0.0,
            )
