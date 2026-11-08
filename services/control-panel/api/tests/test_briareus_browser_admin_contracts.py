from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, patch

from briareus_browser_policy import BrowserRuntimePolicy
from briareus_playwright.external import ExternalBrowserProxyRuntime
from control_panel_api.domain.admin_data.browser import BrowserStatus, ExternalBrowserStatus
from control_panel_api.infrastructure.web import WebAdminClient
from fastmcp.client.client import CallToolResult
from pydantic import ValidationError


class BrowserAdminBoundaryContracts(unittest.IsolatedAsyncioTestCase):
    async def test_status_is_a_model_and_rejects_a_corrupt_remote_field(self) -> None:
        pool = AsyncMock()
        pool.call_tool.return_value = CallToolResult(
            content=[],
            structured_content={"running": True, "pages": [{"page_id": "page-1"}]},
            meta=None,
        )
        with patch(
            "control_panel_api.infrastructure.web.PersistentMcpClientPool", return_value=pool
        ):
            client = WebAdminClient()
        state = await client.status()
        self.assertIsInstance(state, BrowserStatus)
        self.assertEqual(state.pages[0].page_id, "page-1")
        self.assertEqual(
            state.model_dump(exclude_unset=True),
            {
                "running": True,
                "pages": [{"page_id": "page-1"}],
            },
        )
        pool.call_tool.return_value = CallToolResult(
            content=[],
            structured_content={"running": "true"},
            meta=None,
        )
        with self.assertRaises(ValidationError):
            await client.status()

    async def test_external_status_and_action_match_existing_provider_without_network(self) -> None:
        policy = AsyncMock(return_value=BrowserRuntimePolicy(external_enabled=False))
        provider = ExternalBrowserProxyRuntime(policy)
        status_payload = await provider.status()
        state = ExternalBrowserStatus.model_validate(status_payload)
        self.assertFalse(state.connected)
        self.assertEqual(state.model_dump(mode="json", exclude_unset=True), status_payload)
        pool = AsyncMock()
        action_payload = await provider.disconnect()
        pool.call_tool.return_value = CallToolResult(
            content=[],
            structured_content=action_payload,
            meta=None,
        )
        with patch(
            "control_panel_api.infrastructure.web.PersistentMcpClientPool", return_value=pool
        ):
            client = WebAdminClient()
        action = await client.external_disconnect()
        self.assertTrue(action.ok)
        self.assertEqual(action.model_dump(mode="json", exclude_unset=True), action_payload)
