"""Web-owned policy, external capacity and idle-controller regressions."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastmcp.client.client import CallToolResult
from mcp.types import CallToolRequestParams, TextContent
from pydantic import ValidationError
from supervisor_fixture import supervisor_fixture

from modules.web.external_browser_proxy import ExternalBrowserProxyRuntime
from node_protocol.models import RuntimePolicy


class AuditRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_policy_uint32_bound(self) -> None:
        with self.assertRaises(ValidationError):
            RuntimePolicy(web_max_tabs=2**32)
        self.assertEqual(RuntimePolicy(web_max_tabs=2**32 - 1).web_max_tabs, 2**32 - 1)

    async def test_external_explicit_tab_limit_preserves_other_tools(self) -> None:
        owner: ExternalBrowserProxyRuntime[None] = ExternalBrowserProxyRuntime.__new__(
            ExternalBrowserProxyRuntime
        )
        listing = CallToolResult(
            content=[TextContent(type="text", text="- 0: existing (https://example.org)")],
            structured_content=None,
            meta=None,
        )
        lease = AsyncMock()
        lease.call_tool.return_value = listing
        client = Mock(acquire=AsyncMock(return_value=lease))
        with (
            patch.object(owner, "_ensure_client", AsyncMock(return_value=client)),
            patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY": '{"web_max_tabs":1}'}),
        ):
            with self.assertRaisesRegex(RuntimeError, "LIMIT"):
                await owner.guarded_call(
                    CallToolRequestParams(name="browser_tabs", arguments={"action": "new"})
                )
            await owner.guarded_call(CallToolRequestParams(name="browser_snapshot", arguments={}))
        self.assertEqual(lease.call_tool.await_count, 2)

    async def test_parent_idle_kills_without_resuming_expired_uid(self) -> None:
        fixture = supervisor_fixture(self)
        owner = fixture.browser
        owner.profile_key, owner.last_interaction = "owned", 0
        stopped = asyncio.Event()
        stopping = AsyncMock(side_effect=stopped.set)
        with (
            patch.object(owner.process_lease, "pause_expired", AsyncMock()),
            patch.object(owner, "stop", stopping),
            patch.object(owner, "prepare_profile", Mock()),
            patch.dict("os.environ", {"BRIAREUS_RUNTIME_POLICY": '{"web_tab_idle_seconds":0.01}'}),
        ):
            task = asyncio.create_task(owner.watchdog())
            try:
                await asyncio.wait_for(stopped.wait(), 1)
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        stopping.assert_awaited_once()
        fixture.grants.assert_not_awaited()
