"""Adapted Bridge tab restoration: preserve history on failure and enforce limits."""
import asyncio
import unittest
from unittest.mock import AsyncMock, Mock
from modules.web.browser import BrowserManager, BrowserError


class BrowserMenuTests(unittest.IsolatedAsyncioTestCase):
    def browser(self):
        browser = object.__new__(BrowserManager)
        browser._agent_access_enabled = True
        browser._closed_pages = [{"url": "https://example.com/", "label": "Project", "page_agent_access": True}]
        browser._page_labels = {}
        browser._page_agent_access = {}
        page = Mock()
        page.goto = AsyncMock()
        page.close = AsyncMock()
        context = Mock(new_page=AsyncMock(return_value=page))
        browser._ensure_started = AsyncMock(return_value=context)
        browser._require_tab_capacity = Mock()
        browser._register_page = Mock(return_value="restored")
        browser._forget_page = Mock()
        browser._summary = AsyncMock(return_value={"page_id": "restored", "url": "https://example.com/"})
        return browser, page, context

    async def test_restore_uses_old_url_label_and_consumes_only_success(self):
        browser, page, _ = self.browser()
        result = await browser.reopen_closed_page()
        self.assertTrue(result["reopened"])
        page.goto.assert_awaited_once_with("https://example.com/", wait_until="domcontentloaded")
        self.assertEqual(browser._page_labels["restored"], "Project")
        self.assertEqual(browser._closed_pages, [])

    async def test_tab_limit_or_navigation_failure_preserves_restore_history(self):
        browser, page, context = self.browser()
        browser._require_tab_capacity.side_effect = BrowserError("tab limit")
        with self.assertRaises(BrowserError):
            await browser.reopen_closed_page()
        context.new_page.assert_not_awaited()
        self.assertEqual(len(browser._closed_pages), 1)
        browser._require_tab_capacity.side_effect = None
        page.goto.side_effect = RuntimeError("navigation failed")
        with self.assertRaises(RuntimeError):
            await browser.reopen_closed_page()
        page.close.assert_awaited_once()
        self.assertEqual(len(browser._closed_pages), 1)

    async def test_settings_exact_allowlist_and_no_permission_escalation(self):
        browser, page, context = self.browser()
        for section in ("settings", "extensions"):
            await browser.open_settings(section)
            self.assertEqual(page.goto.call_args.args[0], f"chrome://{section}/")
        with self.assertRaises(BrowserError):
            await browser.open_settings("devtools")
        self.assertEqual(context.new_page.await_count, 2)
        browser._closed_pages[-1]["page_agent_access"] = False
        with self.assertRaises(BrowserError):
            await browser.reopen_closed_page()
        self.assertEqual(context.new_page.await_count, 2)

    async def test_operator_uses_same_restoration(self):
        browser, _, _ = self.browser()
        browser._require_operator = Mock()
        browser._operator_lock = asyncio.Lock()
        browser._operator_pages = {}
        await browser.operator_reopen_closed_page("owner")
        self.assertEqual(browser._operator_pages["owner"], "restored")


if __name__ == "__main__":
    unittest.main()
