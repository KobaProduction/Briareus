"""Fresh exact observations repair receipts without replaying native effects."""

import unittest
from dataclasses import replace
from uuid import UUID, uuid4

from node_agent.application.completion import CompletionCandidate, ObserveCompletion
from node_agent.application.readiness import ReadinessFailed, WaitReady
from node_agent.domain.inventory import Allocation, ObservedPlacement
from node_agent.domain.planning import Capacity, PlanningNode, PlanningTarget
from node_agent.domain.readiness import ProcessState


class Store:
    def __init__(self, candidate: CompletionCandidate | None) -> None:
        self.current = candidate
        self.completed: list[tuple[UUID, str]] = []

    async def candidate(self, operation: UUID) -> CompletionCandidate | None:
        del operation
        return self.current

    async def complete(self, operation: UUID, container: str) -> None:
        self.completed.append((operation, container))


class Inventory:
    def __init__(self, node: PlanningNode, items: tuple[ObservedPlacement, ...]) -> None:
        self.current_node = node
        self.items = items
        self.calls: list[str] = []

    def node(self) -> PlanningNode:
        return self.current_node

    async def verify_rootless(self) -> None:
        self.calls.append("verify")

    async def observed(self) -> tuple[ObservedPlacement, ...]:
        self.calls.append("inventory")
        return self.items


class CompletionTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self) -> tuple[UUID, Store, Inventory]:
        operation, node_uuid, placement_uuid = uuid4(), uuid4(), uuid4()
        quota = Allocation(64, 10, 16)
        node = PlanningNode(node_uuid, True, Capacity(Allocation(192, 30, 48), quota))
        target = PlanningTarget(placement_uuid, node_uuid, True, "fingerprint", quota)
        candidate = CompletionCandidate(3, "checking", target, "exact")
        observed = ObservedPlacement("exact", placement_uuid, "fingerprint", quota, True, True)
        return operation, Store(candidate), Inventory(node, (observed,))

    async def test_repairs_exact_receipt_after_verifying_fresh_inventory(self) -> None:
        operation, store, runtime = self.fixture()
        await ObserveCompletion(store, runtime).execute(operation, 3)
        self.assertEqual(runtime.calls, ["verify", "inventory"])
        self.assertEqual(store.completed, [(operation, "exact")])

    async def test_refuses_conflicting_or_incomplete_observations(self) -> None:
        _, _, initial = self.fixture()
        observed = initial.items[0]
        variants = (
            replace(observed, container_id="foreign"),
            replace(observed, fingerprint="stale"),
            replace(observed, running=False),
            replace(observed, ready=False),
            replace(observed, allocation=Allocation(128, 10, 16)),
        )
        for changed in variants:
            with self.subTest(observation=changed):
                operation, store, runtime = self.fixture()
                runtime.items = (
                    replace(changed, deployment_uuid=runtime.items[0].deployment_uuid),
                )
                await ObserveCompletion(store, runtime).execute(operation, 3)
                self.assertEqual(runtime.calls, ["verify", "inventory"])
                self.assertEqual(store.completed, [])

    async def test_stale_terminal_disabled_and_missing_receipts_do_not_observe(self) -> None:
        for state in ("missing", "terminal", "sequence", "disabled", "foreign_node"):
            with self.subTest(state=state):
                operation, store, runtime = self.fixture()
                candidate = store.current
                assert candidate is not None
                if state == "missing":
                    store.current = None
                elif state == "terminal":
                    store.current = replace(candidate, phase="succeeded")
                elif state == "sequence":
                    store.current = replace(candidate, sequence=4)
                elif state == "disabled":
                    runtime.current_node = replace(runtime.current_node, enabled=False)
                else:
                    runtime.current_node = replace(runtime.current_node, node_uuid=uuid4())
                await ObserveCompletion(store, runtime).execute(operation, 3)
                self.assertEqual(runtime.calls, [])
                self.assertEqual(store.completed, [])

    async def test_ambiguous_and_over_budget_inventory_remains_uncommitted(self) -> None:
        for ambiguous in (True, False):
            with self.subTest(ambiguous=ambiguous):
                operation, store, runtime = self.fixture()
                own = runtime.items[0]
                others = (replace(own, deployment_uuid=uuid4()),) * 2
                runtime.items = (own, own) if ambiguous else (own, *others)
                await ObserveCompletion(store, runtime).execute(operation, 3)
                self.assertEqual(store.completed, [])


class Readiness:
    def __init__(self, state: ProcessState, complete: bool) -> None:
        self.current_state, self.is_complete = state, complete
        self.calls: list[str] = []

    async def state(self, container: str) -> ProcessState:
        del container
        self.calls.append("state")
        return self.current_state

    async def complete(self, container: str) -> bool:
        del container
        self.calls.append("complete")
        return self.is_complete


class ReadinessTests(unittest.IsolatedAsyncioTestCase):
    async def test_requires_running_healthy_complete_placement(self) -> None:
        state = ProcessState(True, "healthy", False, None, None)
        runtime = Readiness(state, True)
        await WaitReady(runtime).execute("exact")
        self.assertEqual(runtime.calls, ["state", "complete"])

    async def test_failed_main_never_queries_complete_inventory(self) -> None:
        for state in (
            ProcessState(False, "healthy", False, 3, None),
            ProcessState(True, "unhealthy", False, 3, None),
        ):
            with self.subTest(state=state):
                runtime = Readiness(state, True)
                with self.assertRaises(ReadinessFailed) as failure:
                    await WaitReady(runtime).execute("exact")
                self.assertEqual(failure.exception.state, state)
                self.assertEqual(runtime.calls, ["state"])
