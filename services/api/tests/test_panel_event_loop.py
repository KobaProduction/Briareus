"""Slow owner journals must not block the authenticated Panel transport."""
import asyncio
import time
import unittest
from datetime import UTC,datetime,timedelta
from unittest.mock import patch
from unittest.mock import AsyncMock
from uuid import uuid4
from fastapi import FastAPI
from fastapi.testclient import TestClient
from control_panel_api._oidc_browser import PanelOidcSession
from control_panel_api._oidc_membership import ResolvedPlatformUser,PlatformTeamContext,PlatformProjectContext
from control_panel_api._oidc_origin_policy import BROWSER_ORIGIN
from control_panel_api._panel_events import panel_events_router


class PanelEventLoopTests(unittest.TestCase):
    def test_slow_owner_does_not_delay_rpc_and_delivery_has_sequence(self):
        async def context(request,project):
            expiry=datetime.now(UTC)+timedelta(seconds=25)
            return (PanelOidcSession('https://identity.example','fixture','panel',datetime.now(UTC)+timedelta(minutes=10)),
                ResolvedPlatformUser('https://identity.example','fixture',uuid4(),True,'operator',expiry,(),()))
        async def user(request,project):
            from fastapi.responses import JSONResponse
            return JSONResponse({'fixture':True})
        async def slow(self,proof):
            await asyncio.sleep(1)
            if False:
                yield {}
        app=FastAPI()
        app.include_router(panel_events_router(current_context=context,current_user=user))
        with patch('control_panel_api._owner_events.OwnerSignals.read',slow),TestClient(app) as client:
            with client.websocket_connect('/api/v1/events',headers={'origin':BROWSER_ORIGIN}) as socket:
                frame=socket.receive_json()['params']
                self.assertEqual(frame['sequence'],1)
                self.assertEqual(len(frame['stream_id']),36)
                started=time.monotonic()
                socket.send_json({'jsonrpc':'2.0','id':'heartbeat','method':'system.ping','params':{}})
                reply=socket.receive_json()
                self.assertEqual(reply['id'],'heartbeat')
                self.assertLess(time.monotonic()-started,.7)

    def test_module_preparation_does_not_block_heartbeat(self):
        actor=uuid4()
        async def context(request,project):
            expiry=datetime.now(UTC)+timedelta(seconds=25)
            return (PanelOidcSession('https://identity.example','fixture','panel',datetime.now(UTC)+timedelta(minutes=10)),
                ResolvedPlatformUser('https://identity.example','fixture',actor,True,'operator',expiry,(),()))
        async def user(*args):return None
        async def slow(**kwargs):
            await asyncio.sleep(.5)
            return {"items":[]}
        app=FastAPI();app.include_router(panel_events_router(current_context=context,current_user=user))
        with patch('control_panel_api._node_files.files_call',slow),TestClient(app) as client:
            with client.websocket_connect('/api/v1/events',headers={'origin':BROWSER_ORIGIN}) as socket:
                socket.receive_json()
                socket.send_json({'jsonrpc':'2.0','id':'files','method':'files.resources','params':{}})
                began=time.monotonic()
                socket.send_json({'jsonrpc':'2.0','id':'ping','method':'system.ping','params':{}})
                while True:
                    reply=socket.receive_json()
                    if reply.get('id')=='ping':break
                self.assertLess(time.monotonic()-began,.3)


class TeamRpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_call_metadata_uses_scoped_mcp_topic_and_keeps_owner_cursor(self):
        from control_panel_api._owner_events import OwnerSignals
        project,actor=uuid4(),uuid4()
        proof=ResolvedPlatformUser('https://identity.example','fixture',actor,True,'operator',
            datetime.now(UTC)+timedelta(seconds=25),(),
            (PlatformProjectContext(project,'user',actor,('use_resources','approve_agent_session')),))
        item={'event_id':str(uuid4()),'type':'mcp.call.completed','occurredAt':datetime.now(UTC).isoformat(),
            'actor_id':str(actor),'project_id':str(project),'operation_id':str(uuid4()),'entity_id':str(uuid4()),
            'call':{'hand':'terminal','tool':'job_start','status':'completed','session_uuid':str(uuid4()),
                'node_uuid':str(uuid4()),'placement_uuid':str(uuid4()),'duration_ms':10,'transport':'gateway-mcp'}}
        class Bound:
            async def _call(self,*args):return {'items':[item],'truncated':False,'next':None}
        class Access:
            def for_actor(self,proof):return Bound()
        source=OwnerSignals(Access(),None,None)
        with patch('control_panel_api._owner_events.panel_events.emit',new_callable=AsyncMock) as emit:
            notices=[notice async for notice in source.read(proof)]
            self.assertEqual(emit.await_args.args[:2],('mcp.calls','call.completed'))
            self.assertEqual(emit.await_args.args[2]['tool'],'job_start')
            self.assertEqual(emit.await_args.kwargs['visibility']['project'],str(project))
            self.assertIn(('access',str(project)),source.windows)
            self.assertTrue(source.health[('access',str(project))])

    async def test_release_publication_does_not_block_later_node_phase_events(self):
        from control_panel_api._owner_events import OwnerSignals
        project,actor=uuid4(),uuid4()
        proof=ResolvedPlatformUser('https://identity.example','fixture',actor,True,'operator',
            datetime.now(UTC)+timedelta(seconds=25),(),
            (PlatformProjectContext(project,'user',actor,('use_resources',)),))
        events=[{'event_id':str(uuid4()),'type':kind,'occurredAt':datetime.now(UTC).isoformat(),
            'actor_id':str(actor),'project_id':str(project),'operation_id':str(uuid4()),'entity_id':str(uuid4())}
            for kind in ('node.module.publish','node.module.succeeded')]
        class Resources:
            async def call(self,path,payload):
                return 200,{'items':events,'truncated':False,'next':None}
        source=OwnerSignals(None,None,Resources())
        with patch('control_panel_api._owner_events.panel_events.emit',new_callable=AsyncMock) as emit:
            notices=[item async for item in source.read(proof)]
            self.assertEqual([call.args[1] for call in emit.await_args_list],
                ['node.module.publish','node.module.succeeded'])
            self.assertTrue(source.health[('resources',str(project))])
            self.assertEqual(notices[0]['type'],'source.connected')

    async def test_team_read_does_not_allow_global_inventory_or_foreign_team(self):
        from control_panel_api._panel_rpc import PanelRpc,RpcFailure
        team=uuid4()
        expiry=datetime.now(UTC)+timedelta(seconds=20)
        proof=ResolvedPlatformUser('https://identity.example','fixture',uuid4(),True,'user',expiry,(PlatformTeamContext(team,False),),())
        async def context(socket):return PanelOidcSession(proof.issuer,proof.subject,'panel',expiry),proof
        class Peer:
            async def management(self,payload,**kwargs):
                self.last=payload
                return 200,{'teams':[str(team)]}
        peer=Peer()
        rpc=PanelRpc(context,peer)
        self.assertEqual(await rpc.platform_call(None,'platform.team',{'id':str(team)}),{'teams':[str(team)]})
        self.assertEqual(peer.last['action'],'team.read')
        for method,params in (('platform.inventory',{}),('platform.team',{'id':str(uuid4())})):
            with self.assertRaises(RpcFailure):await rpc.platform_call(None,method,params)
