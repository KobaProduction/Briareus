"""Only exact current original-tool authority may resume private browser work."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

from web_hand.node_supervisor import WebSupervisor


class WebOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.browser = object.__new__(WebSupervisor)
        self.browser.boot = str(uuid4())
        self.browser.operations = {}
        self.browser.lock = asyncio.Lock()
        self.browser.status_warm = True
        self.browser.child_ready = True
        self.browser.metadata = [{"name": "local_browser_open"}]
        self.browser.profile_key = "profile"
        self.permit = SimpleNamespace(actor_uuid=uuid4(),agent_session_uuid=uuid4(),grant_revision=2,
            request_uuid=uuid4(),expires_at=time.time()+4)
        self.identity = (str(self.permit.actor_uuid),str(self.permit.agent_session_uuid),2)
        self.browser.process_lease = SimpleNamespace(identity=self.identity,grant=AsyncMock())
        self.finish = asyncio.Event()

        async def exchange(*args,**kwargs):
            self.assertTrue(kwargs["background"])
            await self.finish.wait()
            return {"result":{"structuredContent":{"page":"owned"},"isError":False}}

        async def stop():
            for record in self.browser.operations.values():
                if record["state"]=="running":
                    record["state"]="interrupted"
                    record["task"].cancel()

        self.browser.exchange=AsyncMock(side_effect=exchange)
        self.browser.stop=AsyncMock(side_effect=stop)
        self.browser.prepare_profile=lambda key:None

    async def asyncTearDown(self):
        await self.browser.stop()

    async def start(self):
        reply=await self.browser.operation_start({"tool":"local_browser_open","arguments":{"url":"https://example.com"}},
            self.permit,self.identity)
        return reply["result"]["structuredContent"]["operation_id"]

    async def test_wrong_tool_identity_and_unrelated_calls_never_renew(self):
        operation=await self.start()
        self.browser.process_lease.grant.reset_mock()
        for identity,tool in ((self.identity,"local_browser_status"),(("foreign",*self.identity[1:]),"local_browser_open")):
            with self.assertRaises(ValueError):
                await self.browser.operation_control("web_operation_poll",{"operation_id":operation,"tool":tool},self.permit,identity)
        with self.assertRaises(ValueError):
            await self.browser.execute("local_browser_status",{},self.permit)
        self.browser.process_lease.grant.assert_not_awaited()
        await self.browser.operation_control("web_operation_poll",{"operation_id":operation,"tool":"local_browser_open"},self.permit,self.identity)
        self.browser.process_lease.grant.assert_awaited_once()
        self.finish.set()
        await self.browser.operations[operation]["task"]
        self.assertEqual(self.browser.operations[operation]["state"],"completed")
        with self.assertRaises(ValueError):
            await self.start()
        self.assertEqual(self.browser.exchange.await_count,1)

    async def test_cancel_never_resumes_and_unknown_handles_never_replay(self):
        operation=await self.start()
        self.browser.process_lease.grant.reset_mock()
        await self.browser.operation_control("web_operation_cancel",{"operation_id":operation},self.permit,self.identity)
        self.assertEqual(self.browser.operations[operation]["state"],"cancelled")
        with self.assertRaises(ValueError):
            await self.browser.operation_control("web_operation_poll",{"operation_id":"old","tool":"local_browser_open"},self.permit,self.identity)
        self.browser.process_lease.grant.assert_not_awaited()

    async def test_expired_and_unprepared_start_cannot_grant(self):
        self.browser.status_warm=False
        with self.assertRaises(ValueError):await self.start()
        self.browser.status_warm=True
        self.permit.expires_at=time.time()-1
        with self.assertRaises(ValueError):await self.start()
        self.browser.process_lease.grant.assert_not_awaited()
