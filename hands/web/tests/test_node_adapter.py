"""Explicit local browser catalogue and trusted profile policy checks."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fastmcp import FastMCP
from common.runtime_annotations import READ_EXTERNAL, WRITE_EXTERNAL
from modules.web.browser_tools import register_browser_tools
from modules.web.browser import BrowserError, BrowserManager
from web_hand.node_runtime import STATIC_TOOLS, browser_metadata
from modules.workspace_compat.legacy_store import WorkspaceFileStore


class NodeCatalogueTests(unittest.IsolatedAsyncioTestCase):
    async def test_dynamic_proxies_cannot_reintroduce_curl_or_ambiguous_tools(self):
        names = ["local_browser_open", "local_devtools_navigate_page", "external_browser_tabs",
                 "external_status", "curl_request", "external_curl_request", "local_devtools_curl", "browser_open"]
        selected = browser_metadata([SimpleNamespace(name=name) for name in names])
        self.assertEqual([item.name for item in selected], names[:4])

    async def test_original_local_browser_signatures_have_explicit_namespace(self):
        mcp = FastMCP("node-web-catalogue-test")
        local = FastMCP("local-managed-browser")
        register_browser_tools(local, READ_EXTERNAL, WRITE_EXTERNAL, browser=None)
        mcp.mount(local, namespace="local")
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        lifecycle = {"external_status", "external_connect", "external_disconnect", "external_reset"}
        self.assertEqual(set(tools), STATIC_TOOLS - lifecycle)
        self.assertEqual(len(tools), 21)
        self.assertFalse(any("curl" in name for name in STATIC_TOOLS))
        self.assertIn("workspace_path", tools["local_browser_screenshot"].parameters["properties"])
        self.assertIn("page_id", tools["local_browser_open"].parameters["properties"])


class NodeBrowserPolicyTests(unittest.TestCase):
    def test_metadata_profile_can_bind_once_before_browser_starts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            browser = BrowserManager(workspace=WorkspaceFileStore(root / "workspace"),
                profile_dir=root / "metadata/profile", executable_path="chromium", headless=True,
                timeout_ms=1000, viewport_width=1280, viewport_height=800,
                max_snapshot_text_chars=1000, max_snapshot_elements=10, developer_access_enabled=True)
            browser.bind_unstarted_profile(root / "actor-session/profile", developer_access_enabled=False)
            self.assertEqual(browser.profile_dir, (root / "actor-session/profile").resolve())
            self.assertFalse(browser.developer_access_enabled)
            browser._browser_process = object()
            with self.assertRaises(BrowserError):
                browser.bind_unstarted_profile(root / "another/profile", developer_access_enabled=True)


if __name__ == "__main__":
    unittest.main()
