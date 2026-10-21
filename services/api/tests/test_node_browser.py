import unittest
import json
import httpx
from unittest.mock import AsyncMock, patch
from pydantic import SecretStr
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4
from fastapi.responses import JSONResponse
from control_panel_api._node_browser import browser_call, prepared_exchange
from control_panel_api._node_terminal import terminal_call
from control_panel_api._panel_rpc import RpcFailure

class BrowserFacadeTests(unittest.IsolatedAsyncioTestCase):
    async def test_analysis_preparing_deadline_guarantees_start_not_dispatched(self):
        calls=[]
        async def exchange(frame):
            calls.append(frame["params"]["name"])
            return {"isError":True,"content":[{"type":"text","text":"NODE_PREPARING"}]}
        clock=SimpleNamespace(time=__import__("unittest").mock.Mock(side_effect=[0,11]))
        with patch("control_panel_api._node_browser.asyncio.get_running_loop",return_value=clock):
            with self.assertRaises(RpcFailure) as caught:
                await prepared_exchange(exchange,{"params":{"name":"analysis_start","arguments":{"engine":"radare2","tool":"radare2_list_binaries","arguments":{}}}},module="reverse",prefix="analysis")
        self.assertEqual(caught.exception.code,"ANALYSIS_PREPARING")
        self.assertFalse(caught.exception.uncertain)
        self.assertEqual(calls,["analysis_tools"])

    async def test_analysis_unknown_sdk_failure_never_retries_or_starts(self):
        calls=[]
        async def exchange(frame):
            calls.append(frame["params"]["name"])
            return {"isError":True,"content":[{"type":"text","text":"NODE_EFFECT_REJECTED_OR_UNAVAILABLE incident=fixture"}]}
        with self.assertRaises(RpcFailure) as caught:
            await prepared_exchange(exchange,{"params":{"name":"analysis_start","arguments":{"engine":"radare2","tool":"radare2_list_binaries","arguments":{}}}},module="reverse",prefix="analysis")
        self.assertEqual(caught.exception.code,"ANALYSIS_PREPARATION_FAILED")
        self.assertEqual(calls,["analysis_tools"])

    async def test_analysis_cold_identity_prepares_readonly_then_starts_once(self):
        calls=[]
        async def exchange(frame):
            name=frame["params"]["name"];calls.append(name)
            if name=="analysis_tools":
                if calls.count(name)==1:return {"isError":True,"content":[{"type":"text","text":"NODE_PREPARING"}]}
                return {"structuredContent":{"engine":"radare2","tools":[{"name":"radare2_list_binaries"}]}}
            return {"structuredContent":{"operation_id":"operation","state":"running"}}
        result=await prepared_exchange(exchange,{"params":{"name":"analysis_start","arguments":{"engine":"radare2","tool":"radare2_list_binaries","arguments":{}}}},module="reverse",prefix="analysis")
        self.assertEqual(calls,["analysis_tools","analysis_tools","analysis_start"])
        self.assertEqual(result["structuredContent"]["state"],"running")

    async def test_resource_escrow_failures_are_rpc_errors(self):
        from control_panel_api._resource_broker import ResourceCredentialUnavailable
        from control_panel_api._oidc_browser import OidcSessionStoreUnavailable
        from control_panel_api._oidc_id_token import OidcIdentityRejected
        expiry=datetime.now(UTC)+timedelta(seconds=30)
        session=SimpleNamespace(issuer="https://issuer",subject="actor",expires_at=expiry)
        proof=SimpleNamespace(issuer="https://issuer",subject="actor",user_uuid=uuid4(),expires_at=expiry)
        command=dict(project_uuid=str(uuid4()),agent_session_uuid=str(uuid4()),expected_grant_revision=1,
            operation_uuid=str(uuid4()),tool="local_browser_status",arguments={})
        for error, code in ((ResourceCredentialUnavailable(),"BROWSER_CREDENTIAL_UNAVAILABLE"),
                            (OidcSessionStoreUnavailable(),"BROWSER_CREDENTIAL_UNAVAILABLE"),
                            (OidcIdentityRejected(),"BROWSER_SIGN_IN_REQUIRED")):
            escrow=SimpleNamespace(resolve=AsyncMock(side_effect=error))
            socket=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resource_credentials=escrow)))
            from control_panel_api._oidc_browser import _SID_COOKIE
            with patch("control_panel_api._node_browser._strict_browser_cookies",return_value={_SID_COOKIE:"ticket"}):
                with self.assertRaises(RpcFailure) as caught:
                    await browser_call(socket=socket,method="browser.command",params=command,
                        current_context=AsyncMock(return_value=(session,proof)),resources=None)
                self.assertEqual(caught.exception.code,code)

    async def test_long_preparation_uses_fresh_owner_proof_at_reply(self):
        expiry=datetime.now(UTC)+timedelta(seconds=60)
        actor=uuid4()
        session=SimpleNamespace(subject="actor",expires_at=expiry)
        initial=SimpleNamespace(issuer="https://issuer",subject="actor",user_uuid=actor,expires_at=expiry)
        fresh=SimpleNamespace(issuer="https://issuer",subject="actor",user_uuid=actor,expires_at=expiry)
        identity=AsyncMock(side_effect=[(session,initial),(session,fresh)])
        class Peer:
            async def call(self,path,payload):
                initial.expires_at=datetime.now(UTC)-timedelta(seconds=1)
                return 200,{"items":[]}
        result=await browser_call(socket=None,method="browser.resources",params={"project_uuid":str(uuid4())},current_context=identity,resources=Peer())
        self.assertEqual(result,{"items":[]})

    async def test_status_waits_for_clean_identity_without_duplicate_effect(self):
        calls=[]
        async def exchange(frame):
            calls.append(frame["params"]["name"])
            return {"isError":True} if len(calls)==1 else {"structuredContent":{"workspace_root":"/project-data"}}
        result=await prepared_exchange(exchange,{"params":{"name":"terminal_status"}},module="terminal",prefix="terminal")
        self.assertEqual(calls,["terminal_status","terminal_status"])
        self.assertEqual(result,{"structuredContent":{"workspace_root":"/project-data"}})

    async def test_cold_initialize_retries_without_dispatching_any_tool(self):
        calls=[]
        async def exchange(frame):
            calls.append(frame["method"])
            if len(calls)==1:raise RpcFailure("TERMINAL_OUTCOME_UNKNOWN",uncertain=True)
            return {"protocolVersion":"2025-03-26"}
        result=await prepared_exchange(exchange,{"method":"initialize"},module="terminal",prefix="terminal")
        self.assertEqual(calls,["initialize","initialize"])
        self.assertEqual(result,{"protocolVersion":"2025-03-26"})

    async def test_lost_terminal_reply_is_uncertain_without_replaying_effect(self):
        expiry=datetime.now(UTC)+timedelta(seconds=60)
        session=SimpleNamespace(issuer="https://issuer",subject="actor",expires_at=expiry)
        proof=SimpleNamespace(issuer=session.issuer,subject=session.subject,user_uuid=uuid4(),expires_at=expiry)
        async def identity(*args):return session,proof
        calls=[]
        async def transport(request):
            frame=json.loads(request.content)
            calls.append(frame["method"])
            if frame["method"]=="tools/call":
                self.assertIsNone(request.extensions["timeout"]["read"])
                raise httpx.ReadTimeout("Lost reply",request=request)
            if "id" not in frame:return httpx.Response(202)
            return httpx.Response(200,json={"jsonrpc":"2.0","id":frame["id"],"result":{}})
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            credential=SimpleNamespace(issuer=session.issuer,subject=session.subject,expires_at=expiry,bearer=SecretStr("fixture"))
            escrow=SimpleNamespace(resolve=AsyncMock(return_value=credential),provider=SimpleNamespace(_client=client))
            socket=SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resource_credentials=escrow)))
            from control_panel_api._node_browser import _SID_COOKIE
            with patch("control_panel_api._node_browser._strict_browser_cookies",return_value={_SID_COOKIE:"fixture"}):
                with self.assertRaises(RpcFailure) as raised:
                    await terminal_call(socket=socket,method="terminal.command",params={
                        "project_uuid":str(uuid4()),"agent_session_uuid":str(uuid4()),"expected_grant_revision":1,
                        "operation_uuid":str(uuid4()),"tool":"job_start","arguments":{"command":"fixture"}},
                        current_context=identity,resources=None)
        self.assertEqual(raised.exception.code,"TERMINAL_OUTCOME_UNKNOWN")
        self.assertTrue(raised.exception.uncertain)
        self.assertEqual(calls,["initialize","notifications/initialized","tools/call"])

    async def test_preparation_retries_read_only_and_executes_mutation_once(self):
        calls=[]
        async def exchange(frame):
            name=frame["params"]["name"]
            calls.append(name)
            if name=="local_browser_status":
                return {"structuredContent":{"result":{"running":calls.count(name)>1}}}
            return {"structuredContent":{"operation_id":"operation"}}
        result=await prepared_exchange(exchange,{"params":{"name":"web_operation_start"}},module="web",prefix="browser")
        self.assertEqual(calls,["local_browser_status","local_browser_status","web_operation_start"])
        self.assertEqual(result,{"structuredContent":{"operation_id":"operation"}})

    async def test_preparation_does_not_retry_denied_status(self):
        calls=[]
        async def exchange(frame):
            calls.append(frame["params"]["name"])
            raise RpcFailure("TERMINAL_PERMISSION_DENIED")
        with self.assertRaises(RpcFailure):
            await prepared_exchange(exchange,{"params":{"name":"workspace_create"}},module="terminal",prefix="terminal")
        self.assertEqual(calls,["terminal_status"])
    async def test_terminal_cannot_call_browser_or_unexposed_tools(self):
        async def identity(*args): self.fail("Invalid terminal tool reached identity")
        common=dict(project_uuid=str(uuid4()),agent_session_uuid=str(uuid4()),expected_grant_revision=1,operation_uuid=str(uuid4()))
        for tool in ("local_browser_open", "workspace_delete", "terminal_exec"):
            with self.assertRaises(RpcFailure):
                await terminal_call(socket=None,method="terminal.command",params=dict(common,tool=tool,arguments={}),current_context=identity,resources=None)

    async def test_terminal_scope_uses_current_actor_and_terminal_route(self):
        expiry=datetime.now(UTC)+timedelta(seconds=10)
        actor=uuid4()
        session=SimpleNamespace(subject="actor",expires_at=expiry)
        proof=SimpleNamespace(issuer="https://issuer",subject="actor",user_uuid=actor,expires_at=expiry)
        async def identity(*args): return session,proof
        class Peer:
            async def call(self,path,payload):
                assert path=="/internal/v1/resources/terminal-scope"
                assert payload["actor_uuid"]==str(actor)
                return 200,{"items":[]}
        result=await terminal_call(socket=None,method="terminal.resources",params={"project_uuid":str(uuid4())},current_context=identity,resources=Peer())
        self.assertEqual(result,{"items":[]})
    async def test_devtools_and_nested_devtools_rejected_before_identity(self):
        async def identity(*args): self.fail("Invalid browser tool reached identity")
        common=dict(project_uuid=str(uuid4()),agent_session_uuid=str(uuid4()),expected_grant_revision=1,operation_uuid=str(uuid4()))
        for tool, arguments in (("local_devtools_evaluate",{}),("web_operation_start",{"tool":"local_devtools_evaluate","arguments":{}})):
            with self.assertRaises(RpcFailure):
                await browser_call(socket=None,method="browser.command",params=dict(common,tool=tool,arguments=arguments),current_context=identity,resources=None)

    async def test_unauthenticated_resources_never_calls_owner(self):
        async def identity(*args): return JSONResponse({},status_code=401)
        class Peer:
            async def call(self,*args): raise AssertionError("Unauthenticated resource access")
        with self.assertRaises(RpcFailure):
            await browser_call(socket=None,method="browser.resources",params={"project_uuid":str(uuid4())},current_context=identity,resources=Peer())

    async def test_resource_reply_rechecked_before_release(self):
        actor=uuid4();project=uuid4();expiry=datetime.now(UTC)+timedelta(seconds=10)
        session=SimpleNamespace(subject="actor",expires_at=expiry)
        proof=SimpleNamespace(issuer="https://issuer",subject="actor",user_uuid=actor,expires_at=expiry)
        calls=0
        async def identity(*args):
            nonlocal calls
            calls+=1
            return (session,proof) if calls==1 else JSONResponse({},status_code=403)
        class Peer:
            async def call(self,path,payload):
                assert path=="/internal/v1/resources/browser-scope"
                assert payload["actor_uuid"]==str(actor)
                return 200,{"items":[]}
        with self.assertRaises(RpcFailure):
            await browser_call(socket=None,method="browser.resources",params={"project_uuid":str(project)},current_context=identity,resources=Peer())
        self.assertEqual(calls,2)
