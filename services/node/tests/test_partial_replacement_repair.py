"""A failed main stop retains networking; only an exact journaled instance is repaired."""

import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from journal_fixture import JournalFixture as Journal
from node_agent.application.completion import ObserveCompletion
from node_agent.application.placement import ApplyPlacement
from node_agent.infrastructure.completion import ControllerCompletionRuntime, JournalCompletionStore
from node_agent.infrastructure.placement import JournalOperationStore
from node_agent.planner import Instance
from test_apply_placement_use_case import RuntimeFixture
from test_reconciliation import fixture

from node_protocol import Deployment, NodeRecord


@dataclass
class ObservationsFixture:
    node: NodeRecord
    engine: RuntimeFixture

    async def observed(self) -> list[Instance]:
        return await self.engine.observed()


class PartialReplacementRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_fresh_core_command_repairs_only_journaled_applied_instance(self) -> None:
        node, spec = fixture()
        for known, matching_limits in ((False, True), (True, False), (True, True)):
            with tempfile.TemporaryDirectory() as folder:
                journal = Journal(Path(folder) / "journal-fixture")
                initial = uuid4()
                (await journal.reserve(initial, 1, spec))
                if known:
                    (await journal.applied(initial, spec, "retained"))
                else:
                    (await journal.phase(initial, "failed", error="UPDATE_FAILED"))

                class RepairEngine(RuntimeFixture):
                    async def resume_applied(self, desired: Deployment) -> str:
                        self.actions.append(("repair", "retained"))
                        self.instances = [
                            Instance(
                                "retained",
                                desired.id,
                                desired.fingerprint,
                                desired.limits,
                                True,
                                True,
                            )
                        ]
                        return "retained"

                engine = RepairEngine()
                actual_limits = (
                    spec.limits
                    if matching_limits
                    else spec.limits.model_copy(update={"cpu_millis": 200})
                )
                engine.instances = [
                    Instance("retained", spec.id, spec.fingerprint, actual_limits, False, False)
                ]
                operation = uuid4()
                await ApplyPlacement(lambda: node, JournalOperationStore(journal), engine).execute(
                    operation, 2, spec
                )
                result = await journal.get(operation)
                assert result is not None
                repaired = known and matching_limits
                self.assertEqual(result.phase, "succeeded" if repaired else "failed")
                self.assertEqual(engine.actions, [("repair", "retained")] if repaired else [])
                (await journal.close())

    async def test_orphan_checking_receipt_completes_from_exact_inventory_without_effect(
        self,
    ) -> None:
        node, spec = fixture()
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "journal-fixture")
            operation = uuid4()
            (await journal.reserve(operation, 1, spec))
            (await journal.phase(operation, "checking", container="known"))
            engine = RuntimeFixture()
            engine.instances = [
                Instance("known", spec.id, spec.fingerprint, spec.limits, True, True)
            ]
            await ObserveCompletion(
                JournalCompletionStore(journal),
                ControllerCompletionRuntime(ObservationsFixture(node, engine)),
            ).execute(operation, 1)
            result = await journal.get(operation)
            assert result is not None
            self.assertEqual(result.phase, "succeeded")
            self.assertEqual(engine.actions, [])
            (await journal.close())

    async def test_orphan_checking_never_adopts_different_native_instance(self) -> None:
        node, spec = fixture()
        with tempfile.TemporaryDirectory() as folder:
            journal = Journal(Path(folder) / "journal-fixture")
            operation = uuid4()
            (await journal.reserve(operation, 1, spec))
            (await journal.phase(operation, "checking", container="known"))
            engine = RuntimeFixture()
            engine.instances = [
                Instance("other", spec.id, spec.fingerprint, spec.limits, True, True)
            ]
            await ObserveCompletion(
                JournalCompletionStore(journal),
                ControllerCompletionRuntime(ObservationsFixture(node, engine)),
            ).execute(operation, 1)
            result = await journal.get(operation)
            assert result is not None
            self.assertEqual(result.phase, "checking")
            self.assertEqual(engine.actions, [])
            (await journal.close())
