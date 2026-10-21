import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock,Mock
from modules.web.browser import BrowserManager,BrowserError
from node_protocol.models import RuntimePolicy

class BrowserLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def owner(self):
        owner=object.__new__(BrowserManager)
        owner.runtime_limits=RuntimePolicy(web_max_tabs=1,web_tab_idle_seconds=0.01)
        owner._pages={"existing":SimpleNamespace(is_closed=lambda:False,close=AsyncMock())}
        owner._page_ids={};owner._page_activity={"existing":0};owner._page_labels={};owner._page_agent_access={};owner._operator_pages={}
        return owner
    async def test_tab_limit_and_popup_do_not_expand_inventory(self):
        owner=self.owner()
        with self.assertRaises(BrowserError):owner._require_tab_capacity()
        popup=SimpleNamespace(close=AsyncMock())
        owner._on_context_page(popup);await asyncio.sleep(0)
        popup.close.assert_awaited_once();self.assertEqual(len(owner._pages),1)
    async def test_idle_closes_and_forgets_page(self):
        owner=self.owner();page=owner._pages["existing"]
        await owner._close_idle_pages()
        page.close.assert_awaited_once();self.assertEqual(owner._pages,{})
    async def test_disabled_limit(self):
        owner=self.owner();owner.runtime_limits=RuntimePolicy(web_max_tabs=None)
        owner._require_tab_capacity()
