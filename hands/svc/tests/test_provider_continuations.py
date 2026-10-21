"""Private continuation authority and configured duration, no provider effects."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
from uuid import uuid4
from hand_runtime.provider_supervisor import ProviderSupervisor
from hand_runtime.deferred_calls import DeferredCalls

class ProviderContinuations(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.done=asyncio.Event()
        self.permit=SimpleNamespace(request_uuid=uuid4(),actor_uuid=uuid4(),agent_session_uuid=uuid4(),grant_revision=2,expires_at=time.time()+4)
        self.identity=(str(self.permit.actor_uuid),str(self.permit.agent_session_uuid),2)
        self.lease=SimpleNamespace(identity=self.identity,grant=AsyncMock(return_value=True))
        self.supervisor=object.__new__(ProviderSupervisor)
        owner=self.supervisor
        owner.module="svc";owner.lock=asyncio.Lock();owner.lease=self.lease;owner.ready=lambda:True;owner.active_context={}
        owner.stop=AsyncMock();owner._schedule_warmup=Mock()
        async def exchange(*args,**kwargs):
            await self.done.wait()
            return {"structuredContent":{"native":True},"isError":False}
        owner.exchange=exchange
        owner.deferred=DeferredCalls("svc",lock=owner.lock,lease=owner.lease,ready=owner.ready,tools=lambda:{"github_clone"},execute=owner.exchange_background,stop=owner.stop,recover=owner._schedule_warmup)
    async def asyncTearDown(self):
        self.supervisor.deferred.interrupt()
        await asyncio.sleep(0)
    async def start(self):
        result=await self.supervisor.execute("svc_operation_start",{"tool":"github_clone","arguments":{"account_id":"mine"}},self.permit,{"accounts":[]})
        await asyncio.sleep(0)
        return result["structuredContent"]["operation_id"]
    async def test_poll_other_account_never_renews(self):
        handle=await self.start();self.lease.grant.reset_mock()
        with self.assertRaises(ValueError):
            await self.supervisor.execute("svc_operation_poll",{"operation_id":handle,"tool":"github_clone","account_id":"foreign"},self.permit,{"accounts":[]})
        self.lease.grant.assert_not_awaited();self.supervisor.stop.assert_not_awaited()
        await self.supervisor.execute("svc_operation_poll",{"operation_id":handle,"tool":"github_clone","account_id":"mine"},self.permit,{"accounts":[]})
        self.lease.grant.assert_awaited_once()
    async def test_explicit_execution_timeout_stops_effect(self):
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":'{"execution_timeout_seconds":0.01}'}):
            handle=await self.start();await asyncio.sleep(0.03)
            self.assertEqual(self.supervisor.deferred.records[handle]["state"],"failed")
            self.supervisor.stop.assert_awaited_once()
    async def test_default_duration_none_and_unrelated_tool_denied(self):
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":"{}"}):
            handle=await self.start();await asyncio.sleep(0.02)
            self.assertEqual(self.supervisor.deferred.records[handle]["state"],"running")
            with self.assertRaises(ValueError):await self.supervisor.execute("github_clone",{},self.permit,{"accounts":[]})
            self.done.set();await asyncio.sleep(0.01)
            self.assertEqual(self.supervisor.deferred.records[handle]["state"],"completed")
            self.assertEqual(self.supervisor.active_context,{})

    async def test_policy_change_stops_before_lease_renewal(self):
        handle=await self.start();self.lease.grant.reset_mock()
        with self.assertRaisesRegex(ValueError,"policy changed"):
            await self.supervisor.execute("svc_operation_poll",{"operation_id":handle,"tool":"github_clone","account_id":"mine"},self.permit,{"accounts":[],"policies":{"disabled":True}})
        self.lease.grant.assert_not_awaited();self.supervisor.stop.assert_awaited_once()

    async def test_lost_start_reply_lookup_does_not_reexecute(self):
        handle=await self.start()
        result=await self.supervisor.execute("svc_operation_poll",{"operation_id":"request:"+str(self.permit.request_uuid),"tool":"github_clone","account_id":"mine"},self.permit,{"accounts":[]})
        self.assertEqual(result["structuredContent"]["operation_id"],handle)
        self.assertEqual(len(self.supervisor.deferred.records),1)
