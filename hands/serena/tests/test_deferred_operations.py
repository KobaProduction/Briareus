"""Private handles never resume another identity/tool or replay an effect."""
import asyncio
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock
from uuid import uuid4

from hand_runtime.deferred_calls import DeferredCalls
from serena_hand.supervisor import SerenaSupervisor


class DeferredOperationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.lock=asyncio.Lock();self.finish=asyncio.Event()
        self.permit=SimpleNamespace(actor_uuid=uuid4(),agent_session_uuid=uuid4(),grant_revision=3,
            request_uuid=uuid4(),expires_at=time.time()+4)
        self.identity=(str(self.permit.actor_uuid),str(self.permit.agent_session_uuid),3)
        self.lease=SimpleNamespace(identity=self.identity,grant=AsyncMock())
        async def execute(*args):
            await self.finish.wait()
            return {'content':[{'type':'text','text':'native result'}],'isError':False}
        async def stop():self.calls.interrupt()
        self.stop=AsyncMock(side_effect=stop);self.recover=Mock()
        self.calls=DeferredCalls('serena',lock=self.lock,lease=self.lease,ready=lambda:True,
            tools=lambda:{'rename_symbol'},execute=execute,stop=self.stop,recover=self.recover)

    async def asyncTearDown(self):
        self.calls.interrupt()
        await asyncio.sleep(0)

    async def start(self):
        result=await self.calls.start({'tool':'rename_symbol','arguments':{'new_name':'Owned'}},self.permit,self.identity)
        return result['structuredContent']['operation_id']

    async def test_wrong_actor_session_revision_tool_and_unknown_handle_do_not_renew(self):
        operation=await self.start();self.lease.grant.reset_mock()
        identities=[('foreign',*self.identity[1:]),(self.identity[0],'other',3),(*self.identity[:2],4)]
        for identity in identities:
            with self.assertRaises(ValueError):
                await self.calls.control('serena_operation_poll',{'operation_id':operation,'tool':'rename_symbol'},self.permit,identity)
        for op,tool in ((operation,'initial_instructions'),('old','rename_symbol')):
            with self.assertRaises(ValueError):
                await self.calls.control('serena_operation_poll',{'operation_id':op,'tool':tool},self.permit,self.identity)
        self.lease.grant.assert_not_awaited()

    async def test_unrelated_native_request_cannot_resume_pending_mutation(self):
        await self.start();self.lease.grant.reset_mock()
        supervisor=object.__new__(SerenaSupervisor);supervisor.lock=self.lock;supervisor.deferred=self.calls
        with self.assertRaises(ValueError):await supervisor.call('initial_instructions',{},self.permit)
        self.lease.grant.assert_not_awaited()
        self.stop.assert_not_awaited()

    async def test_owned_poll_finishes_one_effect_and_duplicate_start_is_rejected(self):
        operation=await self.start();self.lease.grant.reset_mock()
        await self.calls.control('serena_operation_poll',{'operation_id':operation,'tool':'rename_symbol'},self.permit,self.identity)
        self.lease.grant.assert_awaited_once()
        self.finish.set();await self.calls.records[operation]['task']
        result=await self.calls.control('serena_operation_poll',{'operation_id':operation,'tool':'rename_symbol'},self.permit,self.identity)
        self.assertEqual(result['structuredContent']['state'],'completed')
        self.assertIn('result',result['structuredContent'])
        with self.assertRaises(ValueError):await self.start()

    async def test_cancel_stops_without_resume_or_rollback(self):
        operation=await self.start();self.lease.grant.reset_mock()
        result=await self.calls.control('serena_operation_cancel',{'operation_id':operation},self.permit,self.identity)
        self.assertEqual(result['structuredContent']['state'],'cancelled')
        self.lease.grant.assert_not_awaited();self.stop.assert_awaited_once();self.recover.assert_called_once()

    async def test_expired_unknown_recursive_and_concurrent_starts_cannot_dispatch(self):
        for tool in ('unknown','serena_operation_start'):
            with self.assertRaises(ValueError):
                await self.calls.start({'tool':tool,'arguments':{}},self.permit,self.identity)
        self.permit.expires_at=time.time()-1
        with self.assertRaises(ValueError):await self.start()
        self.lease.grant.assert_not_awaited()
        self.permit.expires_at=time.time()+4
        await self.start();self.lease.grant.reset_mock()
        with self.assertRaises(ValueError):await self.start()
        self.lease.grant.assert_not_awaited()
