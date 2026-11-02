"""Terminal decisions and durable receipts retain fail-closed replay ordering."""

import asyncio
import tempfile
import unittest
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from types import MappingProxyType
from uuid import uuid4

from mcp.types import CallToolResult
from pydantic import JsonValue
from terminal_hand.application.execute_operation import ExecuteOperation, UnknownOperationOutcome
from terminal_hand.application.verify_decision import VerifyTerminalDecision
from terminal_hand.application.worker_lifespan import managed_lifespan
from terminal_hand.domain.effect_decision import (
    EffectBinding,
    OperationPrincipal,
    TerminalDecision,
)
from terminal_hand.domain.operation import OperationIdentity
from terminal_hand.infrastructure.operation_history import FileOperationHistory
from terminal_hand.infrastructure.worker_messages import TerminalReply

from runtime_peer.domain.private_effect import PrivateEffectFacts
from runtime_peer.effect_permit import PrivateEffectClaims


class Verifier:
    def __init__(self, decision: TerminalDecision) -> None:
        self.decision = decision

    def verify(self, token: str) -> TerminalDecision:
        self.received = token
        return self.decision


class Worker:
    def __init__(
        self,
        history: FileOperationHistory,
        identity: OperationIdentity,
        *,
        expires: bool = False,
        failure: bool = False,
    ) -> None:
        self.history, self.identity = history, identity
        self.expires, self.failure = expires, failure
        self.current = True
        self.prepared = False
        self.stopped = False
        self.dispatched = False
        self.pending_before_prepare = False

    def authority_current(self) -> bool:
        return self.current

    async def prepare(self) -> None:
        self.prepared = True
        self.pending_before_prepare = self.history.load(self.identity) is not None
        if self.expires:
            self.current = False

    async def stop(self) -> None:
        self.stopped = True

    async def dispatch(self) -> TerminalReply:
        self.dispatched = True
        if self.failure:
            raise ValueError("Interrupted IPC")
        return TerminalReply(
            id=self.identity.operation_uuid, result=CallToolResult(content=[], is_error=False)
        )


class DecisionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.principal = OperationPrincipal(uuid4(), uuid4(), uuid4())
        self.binding = EffectBinding(
            uuid4(), "resource", 123, "terminal_exec", "a" * 64,
            frozenset({"terminal_exec", "lease.renew"}),
        )
        self.decision = TerminalDecision(PrivateEffectFacts(
            token_uuid=uuid4(),
            actor_uuid=self.principal.actor_uuid,
            session_uuid=self.principal.session_uuid,
            operation_uuid=self.principal.operation_uuid,
            issued_at=100, not_before=100, expires_at=105,
            project_uuid=self.binding.project_uuid,
            resource_id="resource", resource_revision=123,
            tool="terminal_exec", arguments_digest="a" * 64, grant_revision=1,
        ))

    def test_current_proof_and_same_lease_are_preserved(self) -> None:
        usecase = VerifyTerminalDecision(Verifier(self.decision))
        self.assertIs(usecase.execute("signed-proof", self.binding, None), self.decision)
        self.assertIs(
            usecase.execute("signed-proof", self.binding, self.decision.lease_identity),
            self.decision,
        )

    def test_rebinding_stale_window_and_changed_lease_are_rejected(self) -> None:
        invalid = [
            TerminalDecision(replace(self.decision.facts, expires_at=106)),
            TerminalDecision(replace(self.decision.facts, not_before=101)),
            TerminalDecision(replace(self.decision.facts, project_uuid=uuid4())),
            TerminalDecision(replace(self.decision.facts, resource_id="other")),
            TerminalDecision(replace(self.decision.facts, resource_revision=124)),
            TerminalDecision(replace(self.decision.facts, tool="job_start")),
            TerminalDecision(replace(self.decision.facts, arguments_digest="b" * 64)),
            TerminalDecision(replace(self.decision.facts, grant_revision=0)),
        ]
        for decision in invalid:
            with self.subTest(decision=decision), self.assertRaises(ValueError):
                VerifyTerminalDecision(Verifier(decision)).execute(
                    "signed-proof", self.binding, None
                )
        with self.assertRaisesRegex(ValueError, "another current session"):
            VerifyTerminalDecision(Verifier(self.decision)).execute(
                "signed-proof", self.binding, (str(uuid4()), str(uuid4()), 1)
            )

    def test_canonical_signed_uuid_is_required(self) -> None:
        identity = uuid4()
        claims: dict[str, JsonValue] = {
            "aud": "briareus:terminal-worker", "iat": 100, "nbf": 100, "exp": 105,
            "jti": str(identity), "project_uuid": str(self.binding.project_uuid),
            "actor_uuid": str(self.principal.actor_uuid),
            "session_uuid": str(self.principal.session_uuid),
            "operation_uuid": str(self.principal.operation_uuid),
            "grant_revision": 1, "tool": "terminal_exec", "arguments_digest": "a" * 64,
            "resource_id": "resource", "resource_revision": 123,
        }
        self.assertEqual(PrivateEffectClaims.model_validate(claims).jti, identity)
        for invalid in (
            str(identity).upper(), identity.hex, "00000000-0000-0000-0000-000000000000",
        ):
            with self.assertRaises(ValueError):
                PrivateEffectClaims.model_validate({**claims, "jti": invalid})


class DurableOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.history = FileOperationHistory(Path(self.temporary.name))
        self.identity = OperationIdentity(uuid4(), "a" * 64)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    async def test_pending_is_durable_before_prepare_and_completed_replays(self) -> None:
        worker = Worker(self.history, self.identity)
        reply = await ExecuteOperation(self.history, worker).execute(self.identity)
        self.assertTrue(worker.pending_before_prepare)
        self.assertTrue(worker.dispatched)
        replay_worker = Worker(self.history, self.identity)
        replay_worker.current = False
        replay = await ExecuteOperation(self.history, replay_worker).execute(self.identity)
        self.assertIsInstance(reply, TerminalReply)
        self.assertEqual(replay, reply)
        self.assertFalse(replay_worker.prepared)
        self.assertFalse(replay_worker.dispatched)

    async def test_expiry_after_prepare_stops_and_leaves_unknown_receipt(self) -> None:
        worker = Worker(self.history, self.identity, expires=True)
        with self.assertRaisesRegex(ValueError, "expired while preparing"):
            await ExecuteOperation(self.history, worker).execute(self.identity)
        self.assertTrue(worker.stopped)
        self.assertFalse(worker.dispatched)
        replay_worker = Worker(self.history, self.identity)
        reply = await ExecuteOperation(self.history, replay_worker).execute(self.identity)
        self.assertIsInstance(reply, UnknownOperationOutcome)
        self.assertFalse(replay_worker.dispatched)

    async def test_failed_dispatch_never_retries_and_fingerprint_mismatch_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "Interrupted IPC"):
            await ExecuteOperation(
                self.history, Worker(self.history, self.identity, failure=True)
            ).execute(self.identity)
        changed = replace(self.identity, fingerprint="b" * 64)
        with self.assertRaisesRegex(ValueError, "changed arguments"):
            await ExecuteOperation(self.history, Worker(self.history, changed)).execute(changed)
        worker = Worker(self.history, self.identity)
        reply = await ExecuteOperation(self.history, worker).execute(self.identity)
        self.assertIsInstance(reply, UnknownOperationOutcome)
        self.assertFalse(worker.dispatched)

    async def test_initial_expiry_never_reserves_or_prepares(self) -> None:
        worker = Worker(self.history, self.identity)
        worker.current = False
        with self.assertRaisesRegex(ValueError, "expired before dispatch"):
            await ExecuteOperation(self.history, worker).execute(self.identity)
        self.assertIsNone(self.history.load(self.identity))
        self.assertFalse(worker.prepared)


class Lifecycle:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def warmup(self) -> None:
        self.events.append("warmup")

    async def watchdog(self) -> None:
        try:
            await asyncio.Event().wait()
        finally:
            self.events.append("watchdog-stop")

    async def close(self) -> None:
        self.events.append("close")


class LifespanTests(unittest.IsolatedAsyncioTestCase):
    async def test_sdk_state_and_teardown_order_are_preserved(self) -> None:
        events: list[str] = []
        state = MappingProxyType({"sdk-owned-state": "value"})

        @asynccontextmanager
        async def sdk(app: str) -> AsyncIterator[Mapping[str, str]]:
            events.append(app)
            try:
                yield state
            finally:
                events.append("sdk-exit")

        async def prepare() -> None:
            events.append("prepare")

        async def probe() -> None:
            events.append("probe")
            await asyncio.sleep(0)

        async with managed_lifespan(sdk, Lifecycle(events), prepare, probe)("sdk-enter") as result:
            self.assertIs(result, state)
            self.assertEqual(events, ["prepare", "warmup", "sdk-enter", "probe"])
        self.assertEqual(events[-3:], ["sdk-exit", "watchdog-stop", "close"])
