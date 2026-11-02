"""Actual journal signatures, no transport retries and fail-closed writer loss."""

import base64
import time
import unittest
from typing import Literal
from uuid import UUID, uuid4

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_agent.domain.placement import OperationConflict
from node_agent.infrastructure.journal_client import JournalUnavailable, SignedJournalClient
from node_agent.infrastructure.remote_journal import Journal

from node_protocol import Deployment, ModuleRelease, ResourceLimits
from node_protocol.control import ControlCommand
from node_protocol.journal import (
    AcquireJournal,
    JournalOperation,
    JournalResult,
    ReadCursor,
    ReserveOperation,
    SignedJournalReply,
    SignedJournalRequest,
    sign_reply,
    verify_request,
)

ReplyMode = Literal["valid", "wrong_key", "wrong_request", "expired", "conflict", "network"]


class RpcDouble:
    def __init__(
        self, node_key: Ed25519PrivateKey, core_key: Ed25519PrivateKey, node: UUID
    ) -> None:
        self.node_key, self.core_key, self.node = node_key, core_key, node
        self.requests: list[SignedJournalRequest] = []
        self.mode: ReplyMode = "valid"
        self.operation: JournalOperation | None = None
        self.closed = False

    async def exchange(self, envelope: SignedJournalRequest) -> SignedJournalReply:
        self.requests.append(envelope)
        request = verify_request(
            envelope, self.node_key.public_key(), node_uuid=self.node, now=int(time.time())
        )
        if self.mode == "network":
            raise JournalUnavailable("Fixture RPC loss")
        result = self._result(envelope)
        status = 200
        if self.mode == "conflict":
            result, status = JournalResult(error="JOURNAL_CONFLICT"), 409
        if self.mode == "wrong_request":
            request = request.model_copy(update={"request_uuid": uuid4()})
        signing_key = Ed25519PrivateKey.generate() if self.mode == "wrong_key" else self.core_key
        now = int(time.time()) - 30 if self.mode == "expired" else int(time.time())
        return sign_reply(request, result, signing_key, status_code=status, now=now)

    def _result(self, envelope: SignedJournalRequest) -> JournalResult:
        payload = envelope.request.payload
        if isinstance(payload, AcquireJournal):
            return JournalResult(lease_epoch=7, lease_expires_at=int(time.time()) + 30)
        if isinstance(payload, ReserveOperation):
            command = payload.core_command
            desired = command.deployment
            if desired is None:
                raise ValueError("Fixture apply command required")
            self.operation = JournalOperation(
                id=str(command.operation_uuid),
                placement=str(desired.id),
                sequence=command.sequence,
                desired=desired,
                fingerprint=desired.fingerprint,
                phase="queued",
            )
        return JournalResult(cursor=42, operation=self.operation)

    async def close(self) -> None:
        self.closed = True


class LockDouble:
    def __init__(self) -> None:
        self.held = False

    def acquire(self) -> None:
        self.held = True

    def release(self) -> None:
        self.held = False


class RemoteJournalTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.node, self.node_key, self.core_key = (
            uuid4(),
            Ed25519PrivateKey.generate(),
            Ed25519PrivateKey.generate(),
        )
        self.rpc = RpcDouble(self.node_key, self.core_key, self.node)
        self.client = SignedJournalClient(
            self.node, self.node_key, self.core_key.public_key(), self.rpc
        )

    async def test_each_read_has_a_fresh_signed_request_and_exact_pinned_reply(self) -> None:
        session = uuid4()
        for _ in range(2):
            result = await self.client.exchange(ReadCursor(), session, 7)
            self.assertEqual(result.cursor, 42)
        self.assertNotEqual(
            self.rpc.requests[0].request.request_uuid, self.rpc.requests[1].request.request_uuid
        )
        self.assertTrue(all(row.request.session_uuid == session for row in self.rpc.requests))

    async def test_forged_stale_conflicting_and_lost_replies_never_retry(self) -> None:
        modes: tuple[ReplyMode, ...] = (
            "wrong_key",
            "wrong_request",
            "expired",
            "conflict",
            "network",
        )
        for mode in modes:
            with self.subTest(mode=mode):
                self.rpc.mode = mode
                before = len(self.rpc.requests)
                expected = OperationConflict if mode == "conflict" else JournalUnavailable
                with self.assertRaises(expected):
                    await self.client.exchange(ReadCursor(), uuid4(), 7)
                self.assertEqual(len(self.rpc.requests), before + 1)

    async def test_acquired_writer_loses_authority_on_uncertain_remote_state(self) -> None:
        lock = LockDouble()
        journal = Journal(self.client, lock)
        try:
            self.assertEqual(await journal.event_cursor(), 42)
            self.assertTrue(lock.held)
            self.assertEqual(self.rpc.requests[0].request.action, "acquire")
            self.assertEqual(self.rpc.requests[1].request.lease_epoch, 7)
            self.rpc.mode = "network"
            with self.assertRaises(JournalUnavailable):
                await journal.event_cursor()
            self.assertTrue(journal.lost.is_set())
            before = len(self.rpc.requests)
            self.rpc.mode = "valid"
            with self.assertRaises(JournalUnavailable):
                await journal.event_cursor()
            self.assertEqual(len(self.rpc.requests), before)
        finally:
            await journal.close()
        self.assertFalse(lock.held)
        self.assertTrue(self.rpc.closed)

    async def test_reservation_requires_exact_core_command_and_reuses_accepted_receipt(
        self,
    ) -> None:
        desired = Deployment(
            id=uuid4(),
            node_uuid=self.node,
            project_uuid=uuid4(),
            limits=ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=100, pids=32),
            release=ModuleRelease(
                module="files",
                image="registry.example/files@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
        )
        now = int(time.time())
        command = ControlCommand(
            node_uuid=self.node,
            operation_uuid=uuid4(),
            sequence=2,
            action="apply",
            deployment=desired,
            issued_at=now,
            expires_at=now + 30,
        )
        signature = base64.b64encode(self.core_key.sign(command.signing_bytes())).decode()
        journal = Journal(self.client, LockDouble())
        try:
            with self.assertRaises(OperationConflict):
                await journal.reserve(command.operation_uuid, 2, desired)
            self.assertEqual(self.rpc.requests, [])
            with journal.authority(command, signature):
                with self.assertRaises(OperationConflict):
                    await journal.reserve(uuid4(), 2, desired)
                first = await journal.reserve(command.operation_uuid, 2, desired)
                repeated = await journal.reserve(command.operation_uuid, 2, desired)
            self.assertEqual(first, repeated)
            reserves = [
                row.request.payload
                for row in self.rpc.requests
                if isinstance(row.request.payload, ReserveOperation)
            ]
            self.assertEqual(len(reserves), 1)
            self.assertEqual(reserves[0].core_command, command)
            self.assertEqual(reserves[0].core_signature, signature)
        finally:
            await journal.close()
