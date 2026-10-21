"""Supervisor ownership, bounded recovery and non-replay of async operations."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from reverse_hand.isolated_supervisor import IsolatedSupervisor


class OperationsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lease = SimpleNamespace(identity=None, grant=AsyncMock(return_value=True), kill=AsyncMock())
        with patch("reverse_hand.isolated_supervisor.ProcessLease", return_value=self.lease):
            self.supervisor = IsolatedSupervisor("unused")
        self.supervisor.child = SimpleNamespace(returncode=None, wait=AsyncMock())
        self.supervisor.prepared = True
        self.permit = SimpleNamespace(actor_uuid=uuid4(), agent_session_uuid=uuid4(),
            grant_revision=1, request_uuid=uuid4(), expires_at=time.time()+5)

    async def asyncTearDown(self):
        await self.supervisor.close()

    async def test_identity_handoff_is_typed_preparing_before_any_engine_effect(self):
        from hand_runtime.errors import NodePreparing
        self.lease.identity=(str(uuid4()),str(uuid4()),1)
        self.lease.grant.return_value=False
        self.supervisor.exchange=AsyncMock()
        with patch.object(self.supervisor,"schedule_recovery") as recover:
            with self.assertRaises(NodePreparing):
                await self.supervisor.call("analysis_start",{"engine":"radare2","tool":"radare2_list_binaries","arguments":{}},self.permit)
            recover.assert_called_once()
        self.supervisor.exchange.assert_not_awaited()
        self.assertEqual(self.supervisor.operations,{})

    async def test_warmup_forwards_transfer_setting_to_child(self):
        self.supervisor.prepared=False
        child=SimpleNamespace(returncode=None,wait=AsyncMock(),stdout=SimpleNamespace(readline=AsyncMock(return_value=b'{"ready":true,"tools":[]}')))
        with patch.dict("os.environ",{"BRIAREUS_PROJECT_TRANSFER":"1"}), patch("reverse_hand.isolated_supervisor.asyncio.create_subprocess_exec",new_callable=AsyncMock,return_value=child) as spawn:
            await self.supervisor.warmup()
            self.assertEqual(spawn.call_args.kwargs["env"]["BRIAREUS_PROJECT_TRANSFER"],"1")
            self.assertTrue(self.supervisor.ready())

    async def test_background_result_requires_exact_owner_and_unknown_ids_never_resume(self):
        finish = asyncio.Event()

        async def execute(*args, **kwargs):
            await finish.wait()
            return {"content": [], "isError": False}

        self.supervisor.exchange = AsyncMock(side_effect=execute)
        started = await self.supervisor.call("analysis_start",
            {"engine": "ghidra", "tool": "import_file", "arguments": {}}, self.permit)
        operation = started["structuredContent"]["operation_id"]
        await asyncio.sleep(0)
        self.assertEqual(self.supervisor.exchange.await_count, 1)
        self.lease.identity = (str(self.permit.actor_uuid), str(self.permit.agent_session_uuid), 1)
        grants = self.lease.grant.await_count
        wrong_actor = SimpleNamespace(**vars(self.permit))
        wrong_actor.actor_uuid = uuid4()
        wrong_session = SimpleNamespace(**vars(self.permit))
        wrong_session.agent_session_uuid = uuid4()
        wrong_revision = SimpleNamespace(**vars(self.permit))
        wrong_revision.grant_revision += 1
        expired = SimpleNamespace(**vars(self.permit))
        expired.expires_at = time.time()-1
        for permit, token in ((wrong_actor, operation), (wrong_session, operation), (wrong_revision, operation),
                              (expired, operation), (self.permit, str(uuid4())+":"+str(uuid4()))):
            with self.assertRaises(ValueError):
                await self.supervisor.call("analysis_poll", {"operation_id": token}, permit)
        self.assertEqual(self.lease.grant.await_count, grants)
        polled = await self.supervisor.call("analysis_poll", {"operation_id": operation}, self.permit)
        self.assertEqual(polled["structuredContent"]["state"], "running")
        finish.set()
        await self.supervisor.operations[operation]["task"]
        result = await self.supervisor.call("analysis_poll", {"operation_id": operation}, self.permit)
        self.assertEqual(result["structuredContent"]["state"], "completed")
        self.assertEqual(self.supervisor.exchange.await_count, 1)

    async def test_cancel_kills_without_resuming_and_does_not_replay(self):
        # A real suspended coroutine keeps the single native exchange active.
        async def pending(*a, **k):
            await asyncio.Event().wait()
        self.supervisor.exchange = AsyncMock(side_effect=pending)
        self.supervisor.schedule_recovery = unittest.mock.Mock()
        result = await self.supervisor.call("analysis_start",
            {"engine": "ghidra", "tool": "import_file", "arguments": {}}, self.permit)
        token = result["structuredContent"]["operation_id"]
        await asyncio.sleep(0)
        grants = self.lease.grant.await_count
        cancelled = await self.supervisor.call("analysis_cancel", {"operation_id": token}, self.permit)
        self.assertEqual(cancelled["structuredContent"]["state"], "cancelled")
        self.assertEqual(self.lease.grant.await_count, grants)
        self.lease.kill.assert_awaited_once()
        self.supervisor.schedule_recovery.assert_called_once()
        self.assertEqual(self.supervisor.exchange.await_count, 1)

    async def test_recovery_retries_metadata_only_and_stops_at_bound(self):
        self.supervisor.warmup = AsyncMock(side_effect=ValueError("private diagnostic"))
        with patch("reverse_hand.isolated_supervisor.RECOVERY_DELAYS", (0, 0, 0)):
            self.supervisor.schedule_recovery()
            first = self.supervisor.warming
            self.supervisor.schedule_recovery()
            self.assertIs(first, self.supervisor.warming)
            await first
        self.assertEqual(self.supervisor.warmup.await_count, 3)


if __name__ == "__main__":
    unittest.main()


class UnifiedBuildInputsTests(unittest.TestCase):
    def test_radare_adapter_uses_current_worktree_with_declared_build_input(self):
        from pathlib import Path
        from node_protocol.catalog import ARTIFACTS
        root=Path(__file__).resolve().parents[3]
        dockerfile=(root/"hands/reverse/Dockerfile.node").read_text()
        self.assertIn("COPY hands/radare2/src/radare2_hand/ /app/src/radare2_hand/",dockerfile)
        self.assertNotIn("COPY --from=radare2-engine /app/src/radare2_hand",dockerfile)
        self.assertIn("hands/radare2/src/radare2_hand/**",ARTIFACTS["reverse"].inputs["paths"])
        ignore=(root/"hands/reverse/Dockerfile.node.dockerignore").read_text()
        self.assertIn("!hands/radare2/src/radare2_hand/**",ignore)
