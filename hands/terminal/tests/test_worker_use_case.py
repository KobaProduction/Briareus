"""Private worker preserves its bounded transport and failure semantics."""

import asyncio
import unittest
from uuid import uuid4

from mcp.types import CallToolResult
from terminal_hand.application.execute_worker import ExecuteWorkerCommand
from terminal_hand.application.worker_contracts import WorkerOutcome
from terminal_hand.infrastructure.worker_codec import decode_command, encode_outcome
from terminal_hand.infrastructure.worker_messages import TerminalReply

from runtime_peer.terminal_receipts import JobRead


class Dispatch:
    def __init__(self, failure: Exception | None = None) -> None:
        self.calls = 0
        self.failure = failure
        self.receipt = JobRead("job-fixture", 0, 2, "ok", 2, "completed", True, False)

    async def execute(self) -> JobRead:
        self.calls += 1
        if self.failure:
            raise self.failure
        return self.receipt


class WorkerUseCaseTests(unittest.IsolatedAsyncioTestCase):
    async def test_original_result_envelope_and_correlation(self) -> None:
        dispatch = Dispatch()
        correlation = uuid4()
        wire = (
            '{"id":"' + str(correlation)
            + '","tool":"terminal_exec","arguments":{}}\n'
        ).encode()
        command = decode_command(wire)
        self.assertEqual(command.id, correlation)
        self.assertEqual(command.call.name, "terminal_exec")
        self.assertEqual(command.call.arguments, {})
        result = await ExecuteWorkerCommand(
            dispatch, frozenset({"terminal_exec"})
        ).execute(command.call.name)
        self.assertEqual(dispatch.calls, 1)
        self.assertIs(result.result, dispatch.receipt)
        reply = TerminalReply.model_validate_json(encode_outcome(command.id, result))
        self.assertEqual(reply.id, correlation)
        assert isinstance(reply.result, CallToolResult)
        self.assertFalse(reply.result.is_error)
        self.assertEqual(reply.result.structured_content, {
            "job_id": "job-fixture", "cursor": 0, "next_cursor": 2,
            "output": "ok", "total_output_bytes": 2, "state": "completed",
            "eof": True, "output_truncated": False,
        })

    async def test_unknown_tool_is_rejected_without_dispatch(self) -> None:
        dispatch = Dispatch()
        with self.assertRaisesRegex(ValueError, "Invalid supervisor command"):
            await ExecuteWorkerCommand(dispatch, frozenset()).execute("escape")
        self.assertEqual(dispatch.calls, 0)

    async def test_operation_failure_is_sanitized(self) -> None:
        correlation = uuid4()
        result = await ExecuteWorkerCommand(
            Dispatch(ValueError("private detail")), frozenset({"exec"})
        ).execute("exec")
        reply = TerminalReply.model_validate_json(encode_outcome(correlation, result))
        self.assertEqual(reply.id, correlation)
        self.assertEqual(reply.error, "TERMINAL_OPERATION_FAILED")
        self.assertNotIn("private detail", encode_outcome(correlation, result))

    async def test_cancellation_propagates(self) -> None:
        class CancelledDispatch:
            async def execute(self) -> JobRead:
                raise asyncio.CancelledError("fixture cancellation")

        with self.assertRaises(asyncio.CancelledError):
            await ExecuteWorkerCommand(CancelledDispatch(), frozenset({"exec"})).execute("exec")

    def test_framing_schema_and_output_budget(self) -> None:
        for invalid in (
            b"{}", b"{}\n", b"x" * 65_537 + b"\n",
            b'{"id":1,"tool":"exec","arguments":[]}\n',
            b'{"id":[1,"request"],"tool":"exec","arguments":{}}\n',
        ):
            with self.assertRaises(ValueError):
                decode_command(invalid)
        correlation = uuid4()
        result = WorkerOutcome(result=JobRead(
            "job-fixture", 0, 1_000_001, "x" * 1_000_001,
            1_000_001, "completed", True, False,
        ))
        reply = TerminalReply.model_validate_json(encode_outcome(correlation, result))
        self.assertEqual(reply.id, correlation)
        self.assertEqual(reply.error, "TERMINAL_OUTPUT_LIMIT")
