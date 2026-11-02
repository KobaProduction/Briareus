"""Adapted Bridge tab restoration: preserve history on failure and enforce limits."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from modules.web.browser import BrowserError, BrowserManager
from web_runtime.browser_models import PageSummary
from web_runtime.domain.browser_policy import BrowserPolicy
from web_runtime.domain.closed_tabs import ClosedTab, ClosedTabs


class BrowserMenuTests(unittest.IsolatedAsyncioTestCase):
    def browser(self) -> tuple[BrowserManager, Mock, Mock, Mock]:
        browser = BrowserManager.__new__(BrowserManager)
        browser._policy = BrowserPolicy()
        browser._closed_pages = ClosedTabs((ClosedTab("https://example.com/", "Project", True),))
        browser._page_labels = {}
        browser._page_agent_access = {}
        page = Mock()
        page.goto = AsyncMock()
        page.close = AsyncMock()
        context = Mock(new_page=AsyncMock(return_value=page))
        self.enterContext(patch.object(browser, "_ensure_started", AsyncMock(return_value=context)))
        capacity = Mock()
        self.enterContext(patch.object(browser, "_require_tab_capacity", capacity))
        self.enterContext(patch.object(browser, "_register_page", Mock(return_value="restored")))
        self.enterContext(patch.object(browser, "_forget_page", Mock()))
        summary = AsyncMock(
            return_value=PageSummary(
                page_id="restored",
                url="https://example.com/",
                title="Project",
                label="Project",
                page_agent_access=True,
                agent_access=True,
            )
        )
        self.enterContext(patch.object(browser, "_summary", summary))
        return browser, page, context, capacity

    async def test_restore_uses_old_url_label_and_consumes_only_success(self) -> None:
        browser, page, _, _ = self.browser()
        result = await browser.reopen_closed_page()
        self.assertTrue(result.reopened)
        page.goto.assert_awaited_once_with("https://example.com/", wait_until="domcontentloaded")
        self.assertEqual(browser._page_labels["restored"], "Project")
        self.assertFalse(browser._closed_pages)

    async def test_tab_limit_or_navigation_failure_preserves_restore_history(self) -> None:
        browser, page, context, capacity = self.browser()
        capacity.side_effect = BrowserError("tab limit")
        with self.assertRaises(BrowserError):
            await browser.reopen_closed_page()
        context.new_page.assert_not_awaited()
        self.assertEqual(len(browser._closed_pages.entries), 1)
        capacity.side_effect = None
        page.goto.side_effect = RuntimeError("navigation failed")
        with self.assertRaises(RuntimeError):
            await browser.reopen_closed_page()
        page.close.assert_awaited_once()
        self.assertEqual(len(browser._closed_pages.entries), 1)

    async def test_settings_exact_allowlist_and_no_permission_escalation(self) -> None:
        browser, page, context, _ = self.browser()
        for section in ("settings", "extensions"):
            await browser.open_settings(section)
            self.assertEqual(page.goto.call_args.args[0], f"chrome://{section}/")
        with self.assertRaises(BrowserError):
            await browser.open_settings("devtools")
        self.assertEqual(context.new_page.await_count, 2)
        browser._closed_pages = ClosedTabs((ClosedTab("https://example.com/", "Project", False),))
        with self.assertRaises(BrowserError):
            await browser.reopen_closed_page()
        self.assertEqual(context.new_page.await_count, 2)

    async def test_restores_settings_search_subpages_and_extension_details(self) -> None:
        browser, page, _, _ = self.browser()
        for url in (
            "chrome://settings/?search=%D1%8F%D0%B7%D1%8B%D0%BA",
            "chrome://settings/languages",
            "chrome://extensions/?id=fixture",
        ):
            with self.subTest(url=url):
                browser._closed_pages = ClosedTabs((ClosedTab(url, "Settings", True),))
                await browser.reopen_closed_page()
                self.assertEqual(page.goto.call_args.args[0], url)
                self.assertFalse(browser._closed_pages)

    def test_internal_url_allowlist_does_not_accept_other_hosts_or_credentials(self) -> None:
        for url in (
            "chrome://settings.evil/",
            "chrome://user@settings/",
            "chrome://settings:1/",
            "chrome://downloads/",
            "chrome://version/?unknown=1",
            "devtools://inspect/",
        ):
            with self.subTest(url=url), self.assertRaises(BrowserError):
                BrowserManager._operator_url(url)

    async def test_operator_uses_same_restoration(self) -> None:
        browser, _, _, _ = self.browser()
        browser._operator_lock = asyncio.Lock()
        browser._operator_pages = {}
        with patch.object(browser, "_require_operator", Mock()):
            await browser.operator_reopen_closed_page("owner")
        self.assertEqual(browser._operator_pages["owner"], "restored")

    async def test_new_blank_tab_never_navigates_to_an_external_url(self) -> None:
        browser, page, context, _ = self.browser()
        page.goto.return_value = None
        with patch.object(browser, "_require_agent_access", Mock()):
            result = await browser.open("about:blank")
        context.new_page.assert_awaited_once()
        page.goto.assert_awaited_once_with("about:blank", wait_until="domcontentloaded")
        self.assertEqual(result.page_id, "restored")
        with self.assertRaises(BrowserError):
            await browser.open("about:blank", "existing")


if __name__ == "__main__":
    unittest.main()
