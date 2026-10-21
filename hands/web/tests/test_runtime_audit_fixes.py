"""Scoped regressions for discovered runtime defects; no live services."""
import asyncio
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,Mock,patch
import httpx
from node_protocol.models import RuntimePolicy
from pydantic import ValidationError
from reverse_hand.project_transfer import register_transfer
from web_hand.node_supervisor import WebSupervisor
from modules.web.external_browser_proxy import ExternalBrowserProxyRuntime

class AuditRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_policy_uint32_bound(self):
        with self.assertRaises(ValidationError):RuntimePolicy(web_max_tabs=2**32)
        self.assertEqual(RuntimePolicy(web_max_tabs=2**32-1).web_max_tabs,2**32-1)

    async def test_raw_upload_uncertain_does_not_repeat_staged(self):
        tools={}
        class MCP:
            def tool(self):
                def register(function):tools[function.__name__]=function;return function
                return register
        provider=SimpleNamespace(_call=AsyncMock())
        register_transfer(MCP(),provider)
        with tempfile.TemporaryDirectory() as temporary:
            source=Path(temporary)/"file.bin";source.write_bytes(b"abc")
            @contextmanager
            def snapshot(*args):yield source,3,"a"*64
            client=SimpleNamespace(post=AsyncMock(side_effect=httpx.ReadTimeout("lost response")))
            context=AsyncMock();context.__aenter__.return_value=client
            with patch.dict("os.environ",{"BRIAREUS_PROJECT_TRANSFER":"1"}),patch("reverse_hand.project_transfer.source_snapshot",snapshot),patch("reverse_hand.project_transfer.httpx.AsyncClient",return_value=context):
                with self.assertRaises(httpx.ReadTimeout):await tools["upload_project_file"]("project","file.bin")
        provider._call.assert_not_awaited()

    async def test_external_explicit_tab_limit_preserves_other_tools(self):
        owner=object.__new__(ExternalBrowserProxyRuntime)
        lease=SimpleNamespace(call_tool=AsyncMock(return_value=SimpleNamespace(is_error=False,content=[SimpleNamespace(text="- 0: existing (https://example.org)")])))
        context=AsyncMock();context.__aenter__.return_value=context;context.call_tool=lease.call_tool
        client=SimpleNamespace(acquire=AsyncMock(return_value=context))
        owner._ensure_client=AsyncMock(return_value=client)
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":'{"web_max_tabs":1}'}):
            with self.assertRaisesRegex(RuntimeError,"LIMIT"):
                await owner.guarded_call("browser_tabs",{"action":"new"})
            await owner.guarded_call("browser_snapshot",{})
        self.assertEqual(lease.call_tool.await_count,2)

    async def test_parent_idle_kills_without_resuming_expired_uid(self):
        owner=object.__new__(WebSupervisor)
        owner.process_lease=SimpleNamespace(pause_expired=AsyncMock(),grant=AsyncMock())
        owner.profile_key="owned";owner.last_interaction=0;owner.lock=asyncio.Lock()
        owner.warming_task=None;owner.child=SimpleNamespace(returncode=None)
        owner.stop=AsyncMock();owner.prepare_profile=Mock()
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":'{"web_tab_idle_seconds":0.01}'}):
            task=asyncio.create_task(owner.watchdog());await asyncio.sleep(0.075);task.cancel()
            with self.assertRaises(asyncio.CancelledError):await task
        owner.stop.assert_awaited_once();owner.process_lease.grant.assert_not_awaited()

    async def test_radare_long_continuation_has_no_hidden_four_second_cap(self):
        from radare2_hand.runtime import Analyzer
        owner=object.__new__(Analyzer);owner.executable="r2";owner.processes=set()
        process=Mock(returncode=0)
        process.stdout=SimpleNamespace(read=AsyncMock(side_effect=[b"[]",b""]))
        process.wait=AsyncMock(return_value=0)
        original=asyncio.timeout;durations=[]
        def timeout(value):durations.append(value);return original(value)
        with patch("radare2_hand.runtime.asyncio.create_subprocess_exec",AsyncMock(return_value=process)),patch("radare2_hand.runtime.asyncio.timeout",side_effect=timeout):
            result=await owner._run(["-q"],None)
        self.assertEqual(result,b"[]");self.assertEqual(durations,[None])
