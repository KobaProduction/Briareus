"""Application ports preserve target-only replacement and journaled recovery."""

import unittest
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from node_agent.application.placement import (
    ApplyPlacement,
    OperationSnapshot,
    RuntimeFailure,
    validate_admission,
)
from node_agent.domain.placement import OperationConflict
from node_agent.planner import Instance

from node_protocol import (
    Deployment,
    ModuleRelease,
    NodeBudget,
    NodeRecord,
    NodeScope,
    ResourceLimits,
)
from node_protocol.diagnostics import FailureDiagnostic


@dataclass
class StoreFixture:
    snapshot: OperationSnapshot
    phases: list[str] = field(default_factory=list)
    known_applied: bool = False
    known_failed: bool = False
    restored: str | None = None
    error: str | None = None

    async def reserve(
        self, _operation: UUID, _sequence: int, _desired: Deployment
    ) -> OperationSnapshot:
        return self.snapshot

    async def current(self, _operation: UUID) -> OperationSnapshot:
        return self.snapshot

    async def phase(
        self,
        _operation: UUID,
        phase: str,
        *,
        container: str | None = None,
        error: str | None = None,
        diagnostic: FailureDiagnostic | None = None,
    ) -> None:
        self.phases.append(phase)
        self.error = error
        self.snapshot = replace(
            self.snapshot,
            phase=phase,
            container=container or self.snapshot.container,
            diagnostic=diagnostic or self.snapshot.diagnostic,
        )

    async def applied(self, operation: UUID, _desired: Deployment, container: str) -> None:
        await self.phase(operation, "succeeded", container=container)

    async def restore(self, _operation: UUID, _previous: Deployment, container: str) -> None:
        self.restored = container

    async def matches_applied(self, _desired: Deployment, _container: str) -> bool:
        return self.known_applied

    async def failed_candidate(
        self, _desired: Deployment, _container: str, _fingerprint: str, _sequence: int
    ) -> bool:
        return self.known_failed


@dataclass
class RuntimeFixture:
    instances: list[Instance] = field(default_factory=list)
    actions: list[tuple[str, str]] = field(default_factory=list)
    fail_pull: bool = False

    async def verify_rootless(self) -> None:
        pass

    async def observed(self) -> list[Instance]:
        return list(self.instances)

    async def resume_applied(self, _desired: Deployment) -> str:
        self.actions.append(("repair", "retained"))
        return "retained"

    async def wait_ready(self, _container: str) -> None:
        pass

    async def pull(self, _desired: Deployment) -> None:
        self.actions.append(("pull", "target"))
        if self.fail_pull:
            raise RuntimeFailure(None, None)

    async def remove_target(self, _desired: Deployment, container: str) -> None:
        self.actions.append(("remove", container))
        self.instances = [item for item in self.instances if item.container_id != container]

    async def stage(self, desired: Deployment) -> str:
        self.actions.append(("create", "target"))
        self.instances.append(
            Instance("created", desired.id, desired.fingerprint, desired.limits, True, True)
        )
        return "created"

    async def diagnose(
        self, _receipt: OperationSnapshot, _desired: Deployment, *, deadline_expired: bool
    ) -> FailureDiagnostic:
        return FailureDiagnostic(
            stage="pulling",
            component="engine",
            reason="readiness_timeout" if deadline_expired else "pull_failed",
        )


class ApplyPlacementTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        limits = ResourceLimits(memory_bytes=128 * 1024**2, cpu_millis=100, pids=32)
        self.node = NodeRecord(
            id=uuid4(),
            name="Fixture",
            scope=NodeScope(kind="shared"),
            enabled=True,
            created_at=datetime.now(UTC),
            budget=NodeBudget(
                total=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=400, pids=128),
                reserved=limits,
            ),
        )
        self.desired = Deployment(
            id=uuid4(),
            node_uuid=self.node.id,
            project_uuid=uuid4(),
            limits=limits,
            release=ModuleRelease(
                module="files",
                image="registry.example/files@sha256:" + "a" * 64,
                lifecycle="sessionful",
            ),
        )
        self.operation = uuid4()
        self.store = StoreFixture(OperationSnapshot(1, "queued", None, None, None))
        self.runtime = RuntimeFixture()
        self.use_case = ApplyPlacement(lambda: self.node, self.store, self.runtime)

    async def test_success_replay_does_not_repeat_native_effects(self) -> None:
        await self.use_case.execute(self.operation, 1, self.desired)
        await self.use_case.execute(self.operation, 1, self.desired)
        self.assertEqual(self.runtime.actions, [("pull", "target"), ("create", "target")])
        self.assertEqual(
            self.store.phases, ["pulling", "stopping", "creating", "checking", "succeeded"]
        )

    async def test_pull_failure_preserves_previous_and_unrelated_processes(self) -> None:
        previous = self.desired.model_copy(
            update={
                "release": self.desired.release.model_copy(
                    update={"image": "registry.example/files@sha256:" + "c" * 64}
                )
            }
        )
        self.store.snapshot = replace(self.store.snapshot, previous=previous)
        self.runtime.instances = [
            Instance("old", previous.id, previous.fingerprint, previous.limits, True, True),
            Instance("other", uuid4(), "d" * 64, self.desired.limits, True, True),
        ]
        self.runtime.fail_pull = True
        await self.use_case.execute(self.operation, 2, self.desired)
        self.assertEqual(self.runtime.actions, [("pull", "target")])
        self.assertEqual(len(self.runtime.instances), 2)
        self.assertEqual(self.store.error, "UPDATE_FAILED")

    async def test_lost_create_receipt_resumes_readiness_without_replacement(self) -> None:
        self.store.snapshot = replace(self.store.snapshot, phase="checking", container="existing")
        self.runtime.instances = [
            Instance(
                "existing",
                self.desired.id,
                self.desired.fingerprint,
                self.desired.limits,
                True,
                False,
            )
        ]
        await self.use_case.execute(self.operation, 1, self.desired)
        self.assertEqual(self.runtime.actions, [])
        self.assertEqual(self.store.snapshot.phase, "succeeded")

    async def test_only_attested_applied_instance_can_resume(self) -> None:
        self.store.known_applied = True
        self.runtime.instances = [
            Instance(
                "retained",
                self.desired.id,
                self.desired.fingerprint,
                self.desired.limits,
                False,
                False,
            )
        ]
        await self.use_case.execute(self.operation, 1, self.desired)
        self.assertEqual(self.runtime.actions, [("repair", "retained")])
        self.assertEqual(self.store.snapshot.phase, "succeeded")

    async def test_unknown_matching_labels_do_not_attest_an_existing_process(self) -> None:
        self.runtime.instances = [
            Instance(
                "unknown",
                self.desired.id,
                self.desired.fingerprint,
                self.desired.limits,
                False,
                False,
            )
        ]
        await self.use_case.execute(self.operation, 1, self.desired)
        self.assertEqual(self.runtime.actions, [])
        self.assertEqual(self.store.snapshot.phase, "failed")

    async def test_disabled_node_is_rechecked_inside_lock_boundary(self) -> None:
        self.node = self.node.model_copy(update={"enabled": False})
        with self.assertRaises(OperationConflict):
            await self.use_case.execute(self.operation, 1, self.desired)
        self.assertEqual(self.runtime.actions, [])

    async def test_project_relocation_is_rejected_before_effects(self) -> None:
        self.store.snapshot = replace(
            self.store.snapshot, previous=self.desired.model_copy(update={"project_uuid": uuid4()})
        )
        with self.assertRaises(OperationConflict):
            await self.use_case.execute(self.operation, 1, self.desired)
        self.assertEqual(self.runtime.actions, [])

    def test_prelock_admission_requires_exact_enabled_node(self) -> None:
        with self.assertRaises(OperationConflict):
            validate_admission(self.node, self.desired.model_copy(update={"node_uuid": uuid4()}))
