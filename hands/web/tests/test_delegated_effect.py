"""A real delegated Tool.run must reach its executor under default policy."""
import hashlib
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock,patch
from uuid import uuid4
from fastmcp.tools import ToolResult
from hand_runtime.node_adapter import NodeDelegatedTool
from node_protocol.control import canonical
from node_protocol.effect import NodeEffectPermit

class DelegatedEffectTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_permit_executes_with_no_default_timeout(self):
        arguments={"page_id":"page-fixture"}
        now=int(time.time())
        permit=NodeEffectPermit(module="web",node_uuid=uuid4(),placement_uuid=uuid4(),project_uuid=uuid4(),workspace_uuid=uuid4(),
            actor_uuid=uuid4(),agent_session_uuid=uuid4(),request_uuid=uuid4(),grant_revision=1,
            fingerprint="a"*64,body_digest="b"*64,bearer_digest="c"*64,
            arguments_digest=hashlib.sha256(canonical(arguments)).hexdigest(),method="tools/call",tool="local_browser_preview",
            resource_id="fixture:"+"x"*80,issued_at=now,expires_at=now+4)
        tool=NodeDelegatedTool(name="local_browser_preview",parameters={"type":"object","properties":{"page_id":{"type":"string"}}})
        tool._module="web"
        tool._execute=AsyncMock(return_value={"content":[{"type":"text","text":"ready"}],"structuredContent":{"ready":True},"isError":False})
        request=SimpleNamespace(scope={"briareus.node_effect":permit})
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":"{}"}),patch("hand_runtime.node_adapter.get_http_request",return_value=request):
            result=await tool.run(arguments)
        self.assertIsInstance(result,ToolResult)
        self.assertEqual(result.content[0].text,"ready")
        tool._execute.assert_awaited_once_with("local_browser_preview",arguments,permit)

    async def test_only_typed_preparation_is_public_retryable_state(self):
        from hand_runtime.errors import NodePreparing
        from fastmcp.exceptions import ToolError
        arguments={}
        now=int(time.time())
        permit=NodeEffectPermit(module="reverse",node_uuid=uuid4(),placement_uuid=uuid4(),project_uuid=uuid4(),workspace_uuid=uuid4(),
            actor_uuid=uuid4(),agent_session_uuid=uuid4(),request_uuid=uuid4(),grant_revision=1,
            fingerprint="a"*64,body_digest="b"*64,bearer_digest="c"*64,
            arguments_digest=hashlib.sha256(canonical(arguments)).hexdigest(),method="tools/call",tool="analysis_tools",
            resource_id="fixture:"+"x"*80,issued_at=now,expires_at=now+4)
        tool=NodeDelegatedTool(name="analysis_tools",parameters={"type":"object","properties":{}})
        tool._module="reverse"
        request=SimpleNamespace(scope={"briareus.node_effect":permit})
        with patch.dict("os.environ",{"BRIAREUS_RUNTIME_POLICY":"{}"}),patch("hand_runtime.node_adapter.get_http_request",return_value=request):
            tool._execute=AsyncMock(side_effect=NodePreparing())
            with self.assertRaisesRegex(ToolError,"^NODE_PREPARING$"):
                await tool.run(arguments)
            tool._execute=AsyncMock(side_effect=ValueError("not a retryable preparation"))
            with self.assertRaisesRegex(ToolError,"^NODE_EFFECT_REJECTED_OR_UNAVAILABLE incident="):
                await tool.run(arguments)
