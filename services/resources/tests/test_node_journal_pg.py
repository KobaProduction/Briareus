"""Actual PostgreSQL durability, fencing, replay, and authority acceptance."""

import base64
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from journal_pg_fixture import JournalPgFixture, pem
from projects._journal_persistence import NodeJournalLeaseRow, NodePairIntentRow
from projects._node_persistence import NodeRow
from projects.application.execution_journal import ConfigurationFact
from projects.domain.execution_journal import JournalConflict, JournalRejected
from projects.infrastructure.node_journal import SqlJournalSession
from projects.infrastructure.node_pairing import remember_pair_intent
from sqlalchemy import select

from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.forward import ForwardProof
from node_protocol.journal import (
    AcquireJournal,
    AdmitForward,
    ApplyOperation,
    ConfigureJournal,
    ForwardTarget,
    GetConfiguration,
    GetOperation,
    JournalOperationEvent,
    PhaseOperation,
    ReadCursor,
    ReadEvents,
    RestoreOperation,
)


class NodeJournalPostgresTests(JournalPgFixture):
    async def test_reservation_reconnect_and_exact_replay_preserve_intent(self) -> None:
        desired = self.spec()
        reserve = await self.intent(desired, 1)
        first = await self.call(reserve)
        self.assertIsNotNone(first.operation)
        self.assertEqual(await self.call(reserve), first)
        await self.reconnect()
        self.assertEqual(
            await self.call(GetOperation(operation_uuid=reserve.core_command.operation_uuid)), first
        )
        changed = reserve.core_command.model_copy(
            update={"deployment": self.spec(placement=desired.id, cpu=300)}
        )
        with self.assertRaises(JournalRejected):
            await self.call(
                reserve.model_copy(
                    update={"core_command": changed, "core_signature": self.signature(changed)}
                )
            )
        forged = reserve.model_copy(update={"core_signature": base64.b64encode(b"x" * 64).decode()})
        with self.assertRaises(JournalRejected):
            await self.call(forged)

    async def test_first_diagnostic_and_rollback_projection_are_durable(self) -> None:
        previous = self.spec()
        original = await self.intent(previous, 1)
        await self.call(original)
        await self.call(
            ApplyOperation(
                operation_uuid=original.core_command.operation_uuid,
                desired=previous,
                container="old-container",
            )
        )
        await self.complete_intent(original.core_command.operation_uuid)
        desired = self.spec(placement=previous.id, cpu=300)
        reserve = await self.intent(desired, 2)
        await self.call(reserve)
        failure = FailureDiagnostic(
            stage="checking", component="worker", reason="oom", oom_killed=True
        )
        await self.call(
            PhaseOperation(
                operation_uuid=reserve.core_command.operation_uuid,
                phase="failed",
                error="UPDATE_FAILED",
                container="failed-container",
                diagnostic=failure,
            )
        )
        await self.call(
            PhaseOperation(
                operation_uuid=reserve.core_command.operation_uuid,
                phase="rolling_back",
                container="failed-container",
                diagnostic=FailureDiagnostic(
                    stage="rolling_back", component="engine", reason="unknown"
                ),
            )
        )
        await self.call(
            RestoreOperation(
                operation_uuid=reserve.core_command.operation_uuid,
                previous=previous,
                container="restored-container",
            )
        )
        await self.call(
            PhaseOperation(
                operation_uuid=reserve.core_command.operation_uuid,
                phase="failed",
                error="UPDATE_FAILED",
                diagnostic=FailureDiagnostic(
                    stage="rolling_back", component="engine", reason="unknown"
                ),
            )
        )
        await self.reconnect()
        result = await self.call(GetOperation(operation_uuid=reserve.core_command.operation_uuid))
        self.assertIsNotNone(result.operation)
        if result.operation is None:
            self.fail("Reserved operation missing after reconnect")
        self.assertEqual(result.operation.diagnostic, failure)
        self.assertEqual(
            (result.operation.phase, result.operation.error), ("failed", "UPDATE_FAILED")
        )
        events = (await self.call(ReadEvents(cursor=0))).events
        self.assertEqual([event.cursor for event in events], list(range(1, len(events) + 1)))
        terminal = events[-1].payload
        if not isinstance(terminal, JournalOperationEvent):
            self.fail("Terminal operation event required")
        self.assertEqual(terminal.diagnostic, failure)
        self.assertEqual(
            [
                event.payload.phase
                for event in events
                if isinstance(event.payload, JournalOperationEvent)
            ][-3:],
            ["failed", "rolling_back", "failed"],
        )

    async def test_gateway_admission_nonce_and_api_replay_never_repeat_effect(self) -> None:
        desired = self.spec()
        reserve = await self.intent(desired, 1)
        await self.call(reserve)
        await self.call(
            ApplyOperation(
                operation_uuid=reserve.core_command.operation_uuid,
                desired=desired,
                container="worker",
            )
        )
        now = int(time.time())
        proof = ForwardProof(
            node_uuid=self.node_uuid,
            placement_uuid=desired.id,
            project_uuid=self.project_uuid,
            agent_session_uuid=uuid4(),
            request_uuid=uuid4(),
            grant_revision=1,
            module="svc",
            fingerprint=desired.fingerprint,
            port=8000,
            body_digest="a" * 64,
            bearer_digest="b" * 64,
            issued_at=now,
            expires_at=now + 15,
        )
        signature = base64.b64encode(self.gateway.sign(proof.signing_bytes())).decode()
        admission = AdmitForward(proof=proof, gateway_signature=signature)
        envelope = self.envelope(admission)
        self.assertEqual((await self.api.execute(envelope, now=now)).container, "worker")
        with self.assertRaises(JournalConflict):
            await self.api.execute(envelope, now=now)
        await self.reconnect()
        with self.assertRaises(JournalConflict):
            await self.call(admission)
        await self.complete_intent(reserve.core_command.operation_uuid)
        next_reserve = await self.intent(self.spec(placement=desired.id, cpu=300), 2)
        await self.call(next_reserve)
        with self.assertRaises(JournalConflict):
            await self.call(ForwardTarget(proof=proof, gateway_signature=signature))

    async def test_configuration_is_monotonic_and_requires_core_authority(self) -> None:
        command = self.command("configure", operation=uuid4(), sequence=2, record=self.record)
        configure = ConfigureJournal(core_command=command, core_signature=self.signature(command))
        result = await self.call(configure)
        self.assertEqual(await self.call(configure), result)
        self.assertEqual((await self.call(ReadCursor())).cursor, 1)
        changed = command.model_copy(
            update={"node_record": self.record.model_copy(update={"enabled": False})}
        )
        with self.assertRaises(JournalConflict):
            await self.call(
                ConfigureJournal(core_command=changed, core_signature=self.signature(changed))
            )
        stale = command.model_copy(update={"sequence": 1})
        with self.assertRaises(JournalConflict):
            await self.call(
                ConfigureJournal(core_command=stale, core_signature=self.signature(stale))
            )
        await self.reconnect()
        self.assertEqual(await self.call(GetConfiguration()), result)

    async def test_writer_takeover_fences_old_requests_and_cached_acquisition(self) -> None:
        old_acquire = self.envelope(AcquireJournal())
        await self.api.execute(old_acquire, now=int(time.time()))
        with self.assertRaises(JournalConflict):
            await self.api.execute(
                self.envelope(AcquireJournal(), session=uuid4()), now=int(time.time())
            )
        async with self.database.transaction() as tx:
            lease = await tx.get(NodeJournalLeaseRow, self.node_uuid)
            if lease is None:
                self.fail("Writer lease missing")
            lease.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        taken = await self.api.execute(
            self.envelope(AcquireJournal(), session=uuid4()), now=int(time.time())
        )
        self.assertEqual(taken.lease_epoch, 2)
        with self.assertRaises(JournalConflict):
            await self.call(ReadCursor())
        with self.assertRaises(JournalConflict):
            await self.api.execute(old_acquire, now=int(time.time()))

    async def test_only_unexpired_operator_pin_allows_read_only_bootstrap(self) -> None:
        async with self.database.transaction() as tx:
            node = await tx.get(NodeRow, self.node_uuid)
            if node is None:
                self.fail("Node missing")
            node.public_key = None
            node.enabled = False
        with self.assertRaises(JournalRejected):
            await self.call(ReadCursor())
        operation = uuid4()
        await remember_pair_intent(
            self.database,
            node_uuid=self.node_uuid,
            operation_uuid=operation,
            actor_uuid=self.actor_uuid,
            project_uuid=self.project_uuid,
            expected_sequence=1,
            endpoint="https://journal-node.example",
            pinned=None,
            public_key=pem(self.node_key),
            fingerprint="a" * 64,
            expiry=datetime.now(UTC) + timedelta(seconds=10),
        )
        self.assertEqual((await self.call(ReadCursor())).cursor, 0)
        command = self.command("configure", operation=uuid4(), sequence=2, record=self.record)
        with self.assertRaises(JournalRejected):
            await self.call(
                ConfigureJournal(core_command=command, core_signature=self.signature(command))
            )
        async with self.database.transaction() as tx:
            intent = await tx.get(NodePairIntentRow, operation)
            if intent is None:
                self.fail("Pending pin missing")
            intent.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        with self.assertRaises(JournalRejected):
            await self.call(ReadCursor())

    async def test_per_node_event_retention_and_cursor_window_are_atomic(self) -> None:
        now = int(time.time())
        async with self.database.transaction() as tx:
            await tx.scalar(select(NodeRow).where(NodeRow.id == self.node_uuid).with_for_update())
            store = SqlJournalSession(tx, self.node_uuid)
            for sequence in range(1, 2051):
                await store.event(ConfigurationFact(str(self.node_uuid), True, sequence), now)
        result = await self.call(ReadEvents(cursor=2))
        self.assertEqual(len(result.events), 128)
        self.assertEqual(result.events[0].cursor, 3)
        self.assertEqual((await self.call(ReadCursor())).cursor, 2050)
        for cursor in (0, 1, 2051):
            with self.assertRaises(JournalConflict):
                await self.call(ReadEvents(cursor=cursor))
