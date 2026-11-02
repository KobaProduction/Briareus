"""Fresh owner decisions, bounded decoding and cancellation remain fail-closed."""

import asyncio
import unittest
from dataclasses import dataclass, field
from uuid import UUID

from bridge.application.admission import AuthorizeConnection
from bridge.domain.admission import (
    ConnectionAdmission,
    ConnectionDecision,
    connection_selectors,
)
from bridge.infrastructure.admission import (
    PrivateAdmissionReply,
    PrivateConnectionDecisions,
    connection_command,
    exact_permit,
)

PROJECT = "12345678-1234-4234-8234-123456789abc"
SESSION = "12345678-1234-4234-8234-123456789abd"


@dataclass
class OwnerFixture:
    reply: PrivateAdmissionReply
    calls: int = 0
    hold: bool = False
    cancelled: bool = False
    started: asyncio.Event = field(default_factory=asyncio.Event)

    async def decide(self, *, bearer: str, body: bytes, module: str) -> PrivateAdmissionReply:
        self.calls += 1
        self.started.set()
        if bearer != "Bearer fixture" or module != "files" or not body:
            raise AssertionError("Exact invocation context required")
        if self.hold:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                self.cancelled = True
                raise
        return self.reply


class ConnectionAdmissionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.admission = ConnectionAdmission(
            "files", "Bearer fixture", UUID(PROJECT), UUID(SESSION), 7
        )
        self.owner = OwnerFixture(PrivateAdmissionReply(200, b'{"allowed":true}'))
        self.use_case = AuthorizeConnection(PrivateConnectionDecisions(self.owner), 0.05)

    async def test_current_decision_is_requested_again_after_prior_permit(self) -> None:
        self.assertEqual(await self.use_case.execute(self.admission), ConnectionDecision.PERMIT)
        self.owner.reply = PrivateAdmissionReply(503, b'{"allowed":true}')
        self.assertEqual(
            await self.use_case.execute(self.admission), ConnectionDecision.UNAVAILABLE
        )
        self.assertEqual(self.owner.calls, 2)

    async def test_only_typed_exact_permit_can_admit(self) -> None:
        for status, body, expected in (
            (401, b"{}", ConnectionDecision.IDENTITY_UNVERIFIED),
            (403, b"{}", ConnectionDecision.ACCESS_DENIED),
            (200, b'{"allowed":1}', ConnectionDecision.UNAVAILABLE),
            (200, b'{"allowed":true,"allowed":true}', ConnectionDecision.UNAVAILABLE),
            (200, b'{"allowed":{"allowed":true}}', ConnectionDecision.UNAVAILABLE),
            (200, b'{"allowed":true,"extra":0}', ConnectionDecision.UNAVAILABLE),
        ):
            with self.subTest(status=status, body=body):
                self.owner.reply = PrivateAdmissionReply(status, body)
                self.assertEqual(await self.use_case.execute(self.admission), expected)

    async def test_timeout_cancels_owner_and_cannot_reuse_prior_permit(self) -> None:
        self.owner.hold = True
        self.assertEqual(
            await self.use_case.execute(self.admission), ConnectionDecision.UNAVAILABLE
        )
        self.assertTrue(self.owner.cancelled)

    async def test_client_cancellation_propagates_and_cancels_owner(self) -> None:
        self.owner.hold = True
        task = asyncio.create_task(self.use_case.execute(self.admission))
        await self.owner.started.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(self.owner.cancelled)

    async def test_missing_owner_is_unavailable(self) -> None:
        self.assertEqual(
            await AuthorizeConnection(None, 1).execute(self.admission),
            ConnectionDecision.UNAVAILABLE,
        )

    def test_command_preserves_exact_owner_wire(self) -> None:
        self.assertEqual(
            connection_command(self.admission),
            (
                f'{{"project_uuid":"{PROJECT}","agent_session_uuid":"{SESSION}",'
                '"action":"mcp.connect","expected_grant_revision":7}'
            ).encode(),
        )

    def test_selector_policy_requires_canonical_identity_and_revision(self) -> None:
        self.assertEqual(connection_selectors(PROJECT, SESSION, "7").grant_revision, 7)
        for project, session, revision in (
            (PROJECT.upper(), SESSION, "7"),
            (PROJECT, SESSION.replace("4234", "1234"), "7"),
            (PROJECT, SESSION, "07"),
            (PROJECT, SESSION, "0"),
            (PROJECT, SESSION, str(2**63)),
            (PROJECT, SESSION, "\u0667"),
        ):
            with (
                self.subTest(project=project, session=session, revision=revision),
                self.assertRaises(ValueError),
            ):
                connection_selectors(project, session, revision)

    def test_decoder_rejects_invalid_or_unbounded_wire(self) -> None:
        for payload in (b"", b"\xff", b"true", b"[true]", b"{" + b" " * 4096):
            with self.subTest(payload=payload[:20]):
                self.assertFalse(exact_permit(payload))
