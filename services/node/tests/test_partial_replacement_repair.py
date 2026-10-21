"""A failed main stop retains networking; only an exact journaled instance is repaired."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from node_agent.docker_engine import DockerEngine, EngineFailure, labels
from node_agent.journal import Journal
from node_agent.planner import Instance
from test_reconciliation import fixture, FakeEngine, ObservedController


class PartialReplacementRepairTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_rejection_never_removes_companion(self):
        _, spec = fixture()
        engine = SimpleNamespace(inspect=AsyncMock(return_value={"Config":{"Labels":labels(spec)}}),
            request=AsyncMock(side_effect=EngineFailure("stop rejected")))
        with patch("node_agent.egress_runtime.remove_companion",new_callable=AsyncMock) as remove:
            with self.assertRaises(EngineFailure):
                await DockerEngine.remove_target(engine,spec,"owned")
            remove.assert_not_awaited()

    async def test_successful_stop_precedes_companion_and_main_removal(self):
        _, spec = fixture();seen=[]
        async def request(method,path,**kwargs):seen.append((method,path))
        async def remove(*args):seen.append(("remove","companion"))
        engine = SimpleNamespace(inspect=AsyncMock(return_value={"Config":{"Labels":labels(spec)}}),request=request)
        with patch("node_agent.egress_runtime.remove_companion",side_effect=remove):
            await DockerEngine.remove_target(engine,spec,"owned")
        self.assertEqual(seen,[("POST","/containers/owned/stop"),("remove","companion"),("DELETE","/containers/owned")])

    async def test_stage_of_exact_running_prior_instance_restores_companion_without_new_main(self):
        _, original=fixture()
        spec=original.model_copy(update={"release":original.release.model_copy(update={"module":"web"})})
        engine=SimpleNamespace(gateway_id="gateway",containers=AsyncMock(return_value=[{
            "Id":"retained","Names":["/"+spec.container_name],"Labels":labels(spec),"State":"running"}]),
            request=AsyncMock())
        with patch("node_agent.egress_runtime.ensure_execution_network",new_callable=AsyncMock), \
             patch("node_agent.egress_runtime.ensure_egress",new_callable=AsyncMock) as ensure:
            self.assertEqual(await DockerEngine.stage(engine,spec),"retained")
            ensure.assert_awaited_once_with(engine,spec)
            engine.request.assert_not_awaited()

    async def test_fresh_core_command_repairs_only_journaled_applied_instance(self):
        node,spec=fixture()
        for known, matching_limits in ((False,True),(True,False),(True,True)):
            with tempfile.TemporaryDirectory() as folder:
                journal=Journal(Path(folder)/"journal.sqlite")
                initial=uuid4();journal.reserve(initial,1,spec)
                if known:journal.applied(initial,spec,"retained")
                else:journal.phase(initial,"failed",error="UPDATE_FAILED")
                class RepairEngine(FakeEngine):
                    async def resume_applied(self,desired):
                        self.actions.append(("repair","retained"))
                        self.instances=[Instance("retained",desired.id,desired.fingerprint,desired.limits,True,True)]
                        return "retained"
                engine=RepairEngine()
                actual_limits=spec.limits if matching_limits else spec.limits.model_copy(update={"cpu_millis":200})
                engine.instances=[Instance("retained",spec.id,spec.fingerprint,actual_limits,False,False)]
                result=await ObservedController(node,engine,journal).apply(uuid4(),2,spec)
                repaired=known and matching_limits
                self.assertEqual(result["phase"],"succeeded" if repaired else "failed")
                self.assertEqual(engine.actions,[("repair","retained")] if repaired else [])
                journal.close()

    async def test_stopped_applied_requires_explicit_resume_and_preserves_container(self):
        _,spec=fixture()
        engine=SimpleNamespace(gateway_id="gateway",containers=AsyncMock(return_value=[{
            "Id":"retained","Names":["/"+spec.container_name],"Labels":labels(spec),"State":"exited"}]),
            inspect=AsyncMock(return_value={"Config":{"Labels":labels(spec)},"State":{"Status":"exited"}}),request=AsyncMock())
        with patch("node_agent.egress_runtime.ensure_execution_network",new_callable=AsyncMock):
            with self.assertRaisesRegex(EngineFailure,"explicit recovery"):
                await DockerEngine.stage(engine,spec)
            engine.request.assert_not_awaited()
            self.assertEqual(await DockerEngine.stage(engine,spec,resume_stopped=True),"retained")
        engine.request.assert_awaited_once_with("POST","/containers/retained/start",accepted=(204,304))

    async def test_orphan_checking_receipt_completes_from_exact_inventory_without_effect(self):
        node,spec=fixture()
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/"journal.sqlite")
            operation=uuid4();journal.reserve(operation,1,spec);journal.phase(operation,"checking",container="known")
            engine=FakeEngine();engine.instances=[Instance("known",spec.id,spec.fingerprint,spec.limits,True,True)]
            result=await ObservedController(node,engine,journal).observe_completion(operation,1)
            self.assertEqual(result["phase"],"succeeded");self.assertEqual(engine.actions,[])
            journal.close()

    async def test_orphan_checking_never_adopts_different_native_instance(self):
        node,spec=fixture()
        with tempfile.TemporaryDirectory() as folder:
            journal=Journal(Path(folder)/"journal.sqlite")
            operation=uuid4();journal.reserve(operation,1,spec);journal.phase(operation,"checking",container="known")
            engine=FakeEngine();engine.instances=[Instance("other",spec.id,spec.fingerprint,spec.limits,True,True)]
            result=await ObservedController(node,engine,journal).observe_completion(operation,1)
            self.assertEqual(result["phase"],"checking");self.assertEqual(engine.actions,[])
            journal.close()
