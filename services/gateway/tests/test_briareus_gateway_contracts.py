from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from fastmcp.client.client import CallToolResult
from gateway.backend_contracts import BackendCallFailure, BackendCallSuccess
from gateway.backend_router import BackendDescriptor, BackendRouter
from mcp.types import Tool


class GatewayEnvelopeContracts(unittest.IsolatedAsyncioTestCase):
    async def test_remote_schema_and_result_stay_opaque_inside_typed_envelopes(self) -> None:
        session = AsyncMock()
        session.list_tools.return_value = [Tool(name="custom", input_schema={"type": "object"})]
        session.call_tool.return_value = CallToolResult(
            content=[], structured_content={"provider_specific": [1, "two"]}, meta=None
        )
        with patch("gateway.backend_router.BackendClientSession", return_value=session):
            descriptor = BackendDescriptor("custom", "http://custom/mcp", "/custom/mcp", "custom")
            router = BackendRouter((descriptor,))
        try:
            inventory = await router.describe()
            self.assertEqual(inventory.backends[0].tool_count, 1)
            tools = await router.tools("custom")
            self.assertEqual(tools.status, "available")
            result = await router.call("custom", "custom")
            self.assertIsInstance(result, BackendCallSuccess)
            assert isinstance(result, BackendCallSuccess)
            self.assertEqual(result.result, {"provider_specific": [1, "two"]})
            session.call_tool.side_effect = TimeoutError("timed out")
            failed = await router.call("custom", "custom")
            self.assertIsInstance(failed, BackendCallFailure)
            assert isinstance(failed, BackendCallFailure)
            self.assertEqual(failed.error_type, "MCP_BACKEND_TIMEOUT")
        finally:
            await router.close()
