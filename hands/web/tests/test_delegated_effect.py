"""A real delegated Tool.run must reach its executor under default policy."""

import hashlib
import time
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastmcp.tools import ToolResult
from mcp.types import CallToolRequest, CallToolRequestParams, CallToolResult, TextContent
from starlette.requests import Request

from hand_runtime.node_adapter import NodeDelegatedTool
from node_protocol.control import canonical
from node_protocol.effect import NodeEffectPermit


class DelegatedEffectTests(unittest.IsolatedAsyncioTestCase):
    async def test_current_permit_executes_with_no_default_timeout(self) -> None:
        arguments = {"page_id": "page-fixture"}
        now = int(time.time())
        permit = NodeEffectPermit(
            module="web",
            node_uuid=uuid4(),
            placement_uuid=uuid4(),
            project_uuid=uuid4(),
            workspace_uuid=uuid4(),
            actor_uuid=uuid4(),
            agent_session_uuid=uuid4(),
            request_uuid=uuid4(),
            grant_revision=1,
            fingerprint="a" * 64,
            body_digest="b" * 64,
            bearer_digest="c" * 64,
            arguments_digest=hashlib.sha256(canonical(arguments)).hexdigest(),
            method="tools/call",
            tool="local_browser_preview",
            resource_id="fixture:" + "x" * 80,
            issued_at=now,
            expires_at=now + 4,
        )
        execute = AsyncMock(
            return_value=CallToolResult(content=[TextContent(type="text", text="ready")])
        )
        tool = NodeDelegatedTool("local_browser_preview", execute, "web")
        call = CallToolRequestParams(name=tool.name, arguments=arguments)
        request = Request(
            {
                "type": "http",
                "briareus.node_effect": permit,
                "briareus.node_call": CallToolRequest(method="tools/call", params=call),
            }
        )
        with (
            patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY": "{}"}),
            patch("hand_runtime.node_adapter.get_http_request", return_value=request),
        ):
            result = await tool.run()
        self.assertIsInstance(result, ToolResult)
        first = result.content[0]
        assert isinstance(first, TextContent)
        self.assertEqual(first.text, "ready")
        execute.assert_awaited_once_with(call, permit)

    async def test_only_typed_preparation_is_public_retryable_state(self) -> None:
        from fastmcp.exceptions import ToolError

        from hand_runtime.errors import NodePreparing

        arguments: dict[str, str] = {}
        now = int(time.time())
        permit = NodeEffectPermit(
            module="reverse",
            node_uuid=uuid4(),
            placement_uuid=uuid4(),
            project_uuid=uuid4(),
            workspace_uuid=uuid4(),
            actor_uuid=uuid4(),
            agent_session_uuid=uuid4(),
            request_uuid=uuid4(),
            grant_revision=1,
            fingerprint="a" * 64,
            body_digest="b" * 64,
            bearer_digest="c" * 64,
            arguments_digest=hashlib.sha256(canonical(arguments)).hexdigest(),
            method="tools/call",
            tool="analysis_tools",
            resource_id="fixture:" + "x" * 80,
            issued_at=now,
            expires_at=now + 4,
        )
        execute = AsyncMock(side_effect=NodePreparing())
        tool = NodeDelegatedTool("analysis_tools", execute, "reverse")
        call = CallToolRequestParams(name=tool.name, arguments=arguments)
        request = Request(
            {
                "type": "http",
                "briareus.node_effect": permit,
                "briareus.node_call": CallToolRequest(method="tools/call", params=call),
            }
        )
        with (
            patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY": "{}"}),
            patch("hand_runtime.node_adapter.get_http_request", return_value=request),
        ):
            with self.assertRaisesRegex(ToolError, "^NODE_PREPARING$"):
                await tool.run()
            execute.side_effect = ValueError("not a retryable preparation")
            with self.assertRaisesRegex(
                ToolError, "^NODE_EFFECT_REJECTED_OR_UNAVAILABLE incident="
            ):
                await tool.run()
