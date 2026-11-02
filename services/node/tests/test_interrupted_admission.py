"""An abandoned queue becomes terminal; an active queue is never replayed or closed."""

import asyncio
import tempfile
import time
import unittest
from pathlib import Path
from uuid import UUID, uuid4

from journal_fixture import JournalFixture
from node_agent.application.control import NodeControl
from node_agent.planner import Instance
from test_reconciliation import fixture

from node_protocol import Deployment, NodeRecord
from node_protocol.control import ControlCommand
from node_protocol.journal import JournalOperation


class UnusedRuntime:
    def __init__(self, record: NodeRecord) -> None:
        self.record = record
        self.lock = asyncio.Lock()

    def node(self) -> NodeRecord:
        return self.record

    def configure(self, record: NodeRecord) -> None:
        del record
        raise AssertionError("Status cannot configure native runtime")

    def validate_budget(self, record: NodeRecord, provisioned: NodeRecord) -> None:
        del record, provisioned
        raise AssertionError("Status cannot reconfigure capacity")

    async def verify_rootless(self) -> None:
        raise AssertionError("Queued status cannot start native execution")

    async def observed(self) -> list[Instance]:
        raise AssertionError("Queued status does not need native effects")

    async def observe_completion(self, operation: UUID, sequence: int) -> None:
        del operation, sequence
        raise AssertionError("Queued operation has no completion to observe")


class Scheduler:
    def __init__(self) -> None:
        self.operations: set[UUID] = set()
        self.scheduled: list[ControlCommand] = []

    def draining(self) -> bool:
        return False

    def active(self, operation: UUID) -> bool:
        return operation in self.operations

    def full(self) -> bool:
        return False

    def schedule(self, command: ControlCommand) -> None:
        self.operations.add(command.operation_uuid)
        self.scheduled.append(command)

    def watch_lease(self) -> None:
        pass


class PausedAdmission(JournalFixture):
    def __init__(self, namespace: Path) -> None:
        super().__init__(namespace)
        self.reserved = asyncio.Event()
        self.release = asyncio.Event()
        self.observed = asyncio.Event()

    async def reserve(
        self, operation: UUID, sequence: int, desired: Deployment
    ) -> JournalOperation:
        row = await super().reserve(operation, sequence, desired)
        self.reserved.set()
        await self.release.wait()
        return row

    async def get(self, operation: UUID) -> JournalOperation | None:
        self.observed.set()
        return await super().get(operation)


class InterruptedAdmissionTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_cannot_close_an_admission_waiting_for_its_journal_ack(self) -> None:
        node, spec = fixture()
        operation = uuid4()
        with tempfile.TemporaryDirectory() as folder:
            journal = PausedAdmission(Path(folder))
            scheduler = Scheduler()
            control = NodeControl(node, UnusedRuntime(node), journal, scheduler)
            now = int(time.time())
            apply = ControlCommand(
                node_uuid=node.id,
                operation_uuid=operation,
                action="apply",
                deployment=spec,
                sequence=1,
                issued_at=now,
                expires_at=now + 20,
            )
            applying = asyncio.create_task(control.execute(apply))
            try:
                await asyncio.wait_for(journal.reserved.wait(), 1)
                status = ControlCommand(
                    node_uuid=node.id,
                    operation_uuid=operation,
                    action="status",
                    sequence=1,
                    issued_at=now,
                    expires_at=now + 20,
                )
                observing = asyncio.create_task(control.execute(status))
                await asyncio.wait_for(journal.observed.wait(), 1)
            finally:
                journal.release.set()
            await applying
            await observing
            row = await journal.get(operation)
            assert row is not None
            self.assertEqual(row.phase, "queued")
            self.assertEqual(scheduler.scheduled, [apply])

    async def test_abandoned_queue_is_closed_without_native_effects(self) -> None:
        node, spec = fixture()
        operation = uuid4()
        with tempfile.TemporaryDirectory() as folder:
            journal = JournalFixture(Path(folder))
            await journal.reserve(operation, 1, spec)
            scheduler = Scheduler()
            control = NodeControl(node, UnusedRuntime(node), journal, scheduler)
            now = int(time.time())
            command = ControlCommand(
                node_uuid=node.id,
                operation_uuid=operation,
                action="status",
                sequence=1,
                issued_at=now,
                expires_at=now + 20,
            )
            reply = await control.execute(command)
            self.assertEqual(reply.status, 200)
            row = await journal.get(operation)
            assert row is not None
            self.assertEqual((row.phase, row.error), ("failed", "CONTROLLER_INTERRUPTED"))
            self.assertEqual(scheduler.scheduled, [])
            await control.execute(command)
            self.assertEqual(scheduler.scheduled, [])

    async def test_live_admission_keeps_queued_task_and_status_never_reschedules_it(self) -> None:
        node, spec = fixture()
        operation = uuid4()
        with tempfile.TemporaryDirectory() as folder:
            journal = JournalFixture(Path(folder))
            scheduler = Scheduler()
            control = NodeControl(node, UnusedRuntime(node), journal, scheduler)
            now = int(time.time())
            apply = ControlCommand(
                node_uuid=node.id,
                operation_uuid=operation,
                action="apply",
                deployment=spec,
                sequence=1,
                issued_at=now,
                expires_at=now + 20,
            )
            self.assertEqual((await control.execute(apply)).status, 202)
            status = ControlCommand(
                node_uuid=node.id,
                operation_uuid=operation,
                action="status",
                sequence=1,
                issued_at=now,
                expires_at=now + 20,
            )
            await control.execute(status)
            row = await journal.get(operation)
            assert row is not None
            self.assertEqual(row.phase, "queued")
            self.assertEqual(scheduler.scheduled, [apply])
