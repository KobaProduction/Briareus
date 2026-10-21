"""Cold profile preparation never needs a longer execution permit."""
import asyncio
import hashlib
import time
import unittest
from contextlib import suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from node_protocol.control import canonical
from web_hand.node_supervisor import WebSupervisor


class StatusPreparationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.permit = SimpleNamespace(actor_uuid=uuid4(), agent_session_uuid=uuid4(), grant_revision=1,
            expires_at=time.time()+4, request_uuid=uuid4())
        self.identity = (str(self.permit.actor_uuid),str(self.permit.agent_session_uuid),1)
        self.browser = object.__new__(WebSupervisor)
        self.browser.lock = asyncio.Lock()
        self.browser.operations = {}
        self.browser.profile_key = hashlib.sha256(canonical(self.identity[:2])).hexdigest()
        self.browser.profile = Path("/browser") / ("session-"+self.browser.profile_key)
        self.browser.process_lease = SimpleNamespace(identity=self.identity,grant=AsyncMock(return_value=True))
        self.browser.child = SimpleNamespace(returncode=None)
        self.browser.child_ready = True
        self.browser.status_task = None
        self.browser.status_warm = False
        self.browser.warming_task = None
        self.finish = asyncio.Event()

        async def exchange(*args,**kwargs):
            await self.finish.wait()
            return {"id":"original-startup","result":{"structuredContent":{"result":{"running":True}},"isError":False}}

        self.browser.exchange = AsyncMock(side_effect=exchange)

        async def stop():
            if self.browser.warming_task is not None and self.browser.warming_task is not asyncio.current_task():
                self.browser.warming_task.cancel()
                with suppress(asyncio.CancelledError, Exception):await self.browser.warming_task
                self.browser.warming_task = None
            self.browser.status_warm = False
            if self.browser.status_task:
                self.browser.status_task.cancel()
                with suppress(asyncio.CancelledError, Exception):await self.browser.status_task
            self.browser.status_task = None
            self.browser.process_lease.identity = None
            self.browser.child = None

        async def start(key):
            self.browser.profile_key = key
            self.browser.profile = Path("/browser") / ("session-"+key)
            self.browser.child = SimpleNamespace(returncode=None)
            self.browser.child_ready = True

        self.browser.stop = AsyncMock(side_effect=stop)
        self.browser.start = AsyncMock(side_effect=start)

    async def asyncTearDown(self):
        await self.browser.stop()

    async def test_status_polls_resume_one_preparation_other_tools_cannot_renew_it(self):
        first = await self.browser.execute("local_browser_status",{},self.permit)
        self.assertTrue(first["result"]["structuredContent"]["result"]["starting"])
        await asyncio.sleep(0)
        self.assertEqual(self.browser.exchange.await_count,1)
        await self.browser.execute("local_browser_status",{},self.permit)
        grants = self.browser.process_lease.grant.await_count
        with self.assertRaises(ValueError):
            await self.browser.execute("local_browser_open",{"url":"https://example.com"},self.permit)
        self.assertEqual(self.browser.process_lease.grant.await_count,grants)
        self.finish.set()
        await self.browser.status_task
        ready = await self.browser.execute("local_browser_status",{},self.permit)
        self.assertTrue(ready["result"]["structuredContent"]["result"]["running"])
        self.assertTrue(self.browser.status_warm)
        self.assertEqual(self.browser.exchange.await_count,1)

    async def test_other_session_destroys_old_preparation_before_starting_its_own(self):
        await self.browser.execute("local_browser_status",{},self.permit)
        await asyncio.sleep(0)
        old = self.browser.status_task
        other = SimpleNamespace(**vars(self.permit));other.agent_session_uuid=uuid4()
        await self.browser.execute("local_browser_status",{},other)
        self.assertTrue(old.cancelled())
        self.browser.stop.assert_awaited_once()
        await self.browser.warming_task
        self.browser.start.assert_awaited_once()
        # Metadata preparation alone does not grant or resume native effects.
        self.assertEqual(self.browser.process_lease.grant.await_count,1)
        await self.browser.execute("local_browser_status",{},other)
        self.assertEqual(self.browser.process_lease.grant.call_args.args[0],
            (str(other.actor_uuid),str(other.agent_session_uuid),1))

    async def test_background_failure_stops_runtime_when_status_is_consumed(self):
        self.browser.exchange = AsyncMock(side_effect=ValueError("private startup failure"))
        await self.browser.execute("local_browser_status",{},self.permit)
        await asyncio.sleep(0)
        with self.assertRaises(ValueError):
            await self.browser.execute("local_browser_status",{},self.permit)
        self.browser.stop.assert_awaited_once()
        self.assertIsNone(self.browser.status_task)

    async def test_metadata_recovery_is_bounded_and_never_executes_a_tool(self):
        self.browser.start = AsyncMock(side_effect=ValueError("metadata unavailable"))
        with patch("web_hand.node_supervisor.asyncio.sleep",AsyncMock()):
            await self.browser.warm_profile(self.browser.profile_key)
        self.assertEqual(self.browser.start.await_count,3)
        self.browser.exchange.assert_not_awaited()


if __name__=="__main__":unittest.main()
