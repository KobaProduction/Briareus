"""Budget changes stay inside bootstrap capacity and preserve running workers."""

import tempfile
import time
import unittest
from pathlib import Path
from uuid import uuid4

from control_fixture import ControlRuntimeFixture, NoEffectsScheduler
from journal_fixture import JournalFixture as Journal
from node_agent.application.control import NodeControl
from node_agent.application.control_results import ControlResult
from node_agent.planner import Instance
from test_reconciliation import fixture

from node_protocol import NodeBudget, NodeRecord, ResourceLimits
from node_protocol.control import ControlCommand


def budget(cpu: int = 2000, memory: int = 2048) -> NodeBudget:
    return NodeBudget(
        total=ResourceLimits(memory_bytes=memory * 1024**2, cpu_millis=cpu, pids=512),
        reserved=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=750, pids=192),
    )


class BudgetTests(unittest.IsolatedAsyncioTestCase):
    async def test_preserves_workers_rejects_ceiling_and_shrink_and_restores_journal(self) -> None:
        original, spec = fixture()
        ceiling = original.model_copy(update={"budget": budget(4000)})
        current = ceiling.model_copy(update={"budget": budget(1000, 1024)})

        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "journal-fixture")
            (await journal.configure(3, current))
            worker = Instance(
                "a" * 64,
                spec.id,
                spec.fingerprint,
                ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=200, pids=32),
                True,
                True,
            )
            runtime = ControlRuntimeFixture(ceiling, [worker])
            service = NodeControl(ceiling, runtime, journal, NoEffectsScheduler())

            async def change(value: NodeRecord, sequence: int) -> ControlResult:
                command = ControlCommand(
                    node_uuid=ceiling.id,
                    operation_uuid=uuid4(),
                    action="configure",
                    sequence=sequence,
                    node_record=value,
                    issued_at=int(time.time()),
                    expires_at=int(time.time()) + 20,
                )
                return await service.execute(command)

            try:
                expanded = current.model_copy(update={"budget": budget(2000)})
                self.assertEqual((await change(expanded, 4)).status, 200)
                self.assertEqual((await change(expanded, 4)).status, 200)
                self.assertEqual(
                    (await change(current.model_copy(update={"budget": budget(5000)}), 5)).status,
                    409,
                )
                too_small = current.model_copy(update={"budget": budget(800, 512)})
                self.assertEqual((await change(too_small, 5)).status, 409)
                configuration = await journal.configuration()
                assert configuration is not None
                self.assertEqual(configuration.sequence, 4)
                # Restart restores the allocation, retaining the larger local ceiling.
                restored = ControlRuntimeFixture(ceiling, [worker])
                await NodeControl(ceiling, restored, journal, NoEffectsScheduler()).initialize()
                self.assertEqual(restored.record, expanded)
                self.assertEqual(runtime.instances, [worker])
                with self.assertRaises(ValueError):
                    invalid = NodeControl(
                        ceiling.model_copy(update={"budget": budget(1000, 1024)}),
                        ControlRuntimeFixture(ceiling),
                        journal,
                        NoEffectsScheduler(),
                    )
                    await invalid.execute(
                        ControlCommand(
                            node_uuid=ceiling.id,
                            operation_uuid=uuid4(),
                            action="inventory",
                            sequence=1,
                            issued_at=int(time.time()),
                            expires_at=int(time.time()) + 20,
                        )
                    )
            finally:
                (await journal.close())
