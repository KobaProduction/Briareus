"""Critical replacement and operation-journal boundaries; no live Docker access."""
import asyncio
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from node_protocol import Deployment, ModuleRelease, NodeBudget, NodeRecord, NodeScope, ResourceLimits
from node_agent.controller import Controller
from node_agent.docker_engine import EngineFailure, container_config
from node_agent.journal import Journal, OperationConflict
from node_agent.planner import Instance, plan


def limits(memory=128):
    return ResourceLimits(memory_bytes=memory * 1024**2, cpu_millis=100, pids=32)


def fixture():
    node = NodeRecord(id=uuid4(), name="Node", scope=NodeScope(kind="shared"),
        budget=NodeBudget(total=ResourceLimits(memory_bytes=384 * 1024**2, cpu_millis=400, pids=128),
                          reserved=limits(128)), enabled=True,
        created_at=datetime.now(UTC))
    spec = Deployment(id=uuid4(), node_uuid=node.id, project_uuid=uuid4(),
        release=ModuleRelease(module="files", image="registry.example/files@sha256:" + "a" * 64,
                              lifecycle="sessionful"), limits=limits())
    return node, spec


class FakeEngine:
    def __init__(self):
        self.instances = []
        self.actions = []
        self.fail_pull = False

    async def verify_rootless(self):
        pass

    async def pull(self, spec):
        self.actions.append(("pull", spec.id))
        if self.fail_pull:
            raise EngineFailure("delivery failed")

    async def remove_target(self, spec, container):
        self.actions.append(("remove", container))
        self.instances = [item for item in self.instances if item.container_id != container]

    async def stage(self, spec):
        self.actions.append(("create", spec.id))
        cid = "b" * 64
        self.instances.append(Instance(cid, spec.id, spec.fingerprint, spec.limits, True, True))
        return cid


class ObservedController(Controller):
    async def observed(self):
        return list(self.engine.instances)

    async def wait_ready(self, container):
        if container not in {item.container_id for item in self.engine.instances}:
            raise EngineFailure("not ready")


class ReconciliationTests(unittest.TestCase):
    def test_replacement_does_not_require_double_capacity(self):
        node, spec = fixture()
        old = Instance("old", spec.id, "old", spec.limits, True, True)
        unrelated = Instance("other", uuid4(), "other", spec.limits, True, True)
        self.assertEqual(plan(node, spec, [old, unrelated]).action, "replace")
        self.assertEqual(plan(node, spec, [old, unrelated,
            Instance("third", uuid4(), "third", spec.limits, True, True)]).action, "blocked")

    def test_worker_configuration_has_no_host_authority(self):
        _, spec = fixture()
        cfg = container_config(spec)
        host = cfg["HostConfig"]
        self.assertFalse(host["Privileged"])
        self.assertEqual(host["CapDrop"], ["ALL"])
        self.assertEqual(host["Memory"], spec.limits.memory_bytes)
        self.assertEqual(host["NanoCpus"], 100_000_000)
        self.assertEqual(host["PidsLimit"], spec.limits.pids)
        self.assertFalse({"Binds", "Devices", "PortBindings", "VolumesFrom"} & host.keys())
        self.assertNotEqual(cfg["User"].split(":")[0], "0")

    def test_retry_and_stale_commands(self):
        _, spec = fixture()
        with tempfile.TemporaryDirectory() as directory:
            journal = Journal(Path(directory) / "state.sqlite")
            operation = uuid4()
            journal.reserve(operation, 1, spec)
            self.assertEqual(journal.reserve(operation, 1, spec)["phase"], "queued")
            with self.assertRaises(OperationConflict):
                journal.reserve(uuid4(), 2, spec)
            journal.phase(operation, "failed", error="UPDATE_FAILED")
            with self.assertRaises(OperationConflict):
                journal.reserve(uuid4(), 1, spec)
            journal.reserve(uuid4(), 2, spec)
            with self.assertRaises(OperationConflict):
                Journal(Path(directory) / "state.sqlite")
            journal.close()

    def test_success_replays_without_creating_again(self):
        async def scenario():
            node, spec = fixture()
            with tempfile.TemporaryDirectory() as directory:
                journal = Journal(Path(directory) / "state.sqlite")
                engine = FakeEngine()
                controller = ObservedController(node, engine, journal)
                operation = uuid4()
                self.assertEqual((await controller.apply(operation, 1, spec))["phase"], "succeeded")
                self.assertEqual((await controller.apply(operation, 1, spec))["phase"], "succeeded")
                self.assertEqual([a[0] for a in engine.actions], ["pull", "create"])
                journal.close()
        asyncio.run(scenario())

    def test_target_only_and_pull_failure_preserves_everything(self):
        async def scenario():
            node, spec = fixture()
            old = spec.model_copy(update={"release": spec.release.model_copy(
                update={"image": "registry.example/files@sha256:" + "c" * 64})})
            with tempfile.TemporaryDirectory() as directory:
                journal = Journal(Path(directory) / "state.sqlite")
                initial = uuid4()
                journal.reserve(initial, 1, old)
                journal.applied(initial, old, "old")
                engine = FakeEngine()
                engine.instances = [Instance("old", spec.id, old.fingerprint, old.limits, True, True),
                    Instance("browser", uuid4(), "other", spec.limits, True, True)]
                controller = ObservedController(node, engine, journal)
                engine.fail_pull = True
                self.assertEqual((await controller.apply(uuid4(), 2, spec))["phase"], "failed")
                self.assertEqual(len(engine.instances), 2)
                engine.fail_pull = False
                self.assertEqual((await controller.apply(uuid4(), 3, spec))["phase"], "succeeded")
                self.assertIn("browser", [item.container_id for item in engine.instances])
                self.assertEqual([a for a in engine.actions if a[0] == "remove"], [("remove", "old")])
                journal.close()
        asyncio.run(scenario())

    def test_controller_recovers_readiness_without_replacing_process(self):
        async def scenario():
            node, spec = fixture()
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "state.sqlite"
                journal = Journal(path)
                operation = uuid4()
                journal.reserve(operation, 1, spec)
                journal.phase(operation, "checking", container="existing")
                journal.close()
                journal = Journal(path)
                engine = FakeEngine()
                engine.instances = [Instance("existing", spec.id, spec.fingerprint,
                                             spec.limits, True, False)]
                receipt = await ObservedController(node, engine, journal).apply(operation, 1, spec)
                self.assertEqual(receipt["phase"], "succeeded")
                self.assertEqual(receipt["container"], "existing")
                self.assertEqual(engine.actions, [])
                journal.close()
        asyncio.run(scenario())

    def test_new_operation_replaces_only_its_journaled_failed_candidate(self):
        async def scenario():
            node,spec=fixture()
            for known in (False,True):
                with tempfile.TemporaryDirectory() as directory:
                    journal=Journal(Path(directory)/"state.sqlite")
                    initial=uuid4()
                    journal.reserve(initial,1,spec)
                    journal.phase(initial,"failed",container="candidate" if known else None,error="UPDATE_FAILED")
                    engine=FakeEngine()
                    engine.instances=[Instance("candidate",spec.id,spec.fingerprint,spec.limits,True,False)]
                    result=await ObservedController(node,engine,journal).apply(uuid4(),2,spec)
                    self.assertEqual(result["phase"],"succeeded" if known else "failed")
                    self.assertEqual([item[0] for item in engine.actions],
                        ["pull","remove","create"] if known else [])
                    journal.close()
        asyncio.run(scenario())


if __name__ == "__main__":
    unittest.main()
