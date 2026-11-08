from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_json_values import JsonObject
from briareus_playwright.browser import BrowserManager
from briareus_playwright.session import BrowserSession
from briareus_playwright.settings import BrowserSettings
from fastmcp import FastMCP
from fastmcp.client import Client


def private_server(name: str, _management: ControlPanelClient | None = None) -> FastMCP[None]:
    return FastMCP(name)


class PlaywrightModeContracts(unittest.IsolatedAsyncioTestCase):
    async def test_one_playwright_mcp_keeps_internal_and_external_contexts_distinct(self) -> None:
        upstream: FastMCP[None] = FastMCP("External Playwright")

        @upstream.tool
        def browser_open(url: str) -> JsonObject:
            return {"mode": "external", "url": url}

        with tempfile.TemporaryDirectory() as directory:
            browser = MagicMock(spec=BrowserManager)
            browser.open.return_value = {"mode": "internal"}
            session = BrowserSession(
                settings=BrowserSettings(profile_dir=Path(directory)), browser=browser
            )
            external = MagicMock()
            external.server = upstream
            try:
                with (
                    patch(
                        "briareus_playwright.session.create_browser_session", return_value=session
                    ),
                    patch(
                        "briareus_hand_runtime.runtime_common.build_private_mcp",
                        side_effect=private_server,
                    ),
                    patch(
                        "briareus_playwright.external.ExternalBrowserProxyRuntime",
                        return_value=external,
                    ),
                ):
                    runtime = importlib.import_module("briareus_playwright.runtime")
                self.assertEqual(runtime.mcp.name, "playwright")
                async with Client(runtime.mcp) as client:
                    names = {tool.name for tool in await client.list_tools()}
                    self.assertIn("browser_open", names)
                    self.assertIn("external_browser_open", names)
                    self.assertIn("browser_external_connect", names)
                    self.assertFalse(any(name.startswith("devtools_") for name in names))
                    internal = await client.call_tool(
                        "browser_open", {"url": "https://internal.example"}
                    )
                    remote = await client.call_tool(
                        "external_browser_open", {"url": "https://external.example"}
                    )
                    self.assertEqual(internal.data, {"mode": "internal"})
                    self.assertEqual(
                        remote.data, {"mode": "external", "url": "https://external.example"}
                    )
                    browser.open.assert_awaited_once_with("https://internal.example", "")
            finally:
                sys.modules.pop("briareus_playwright.runtime", None)
