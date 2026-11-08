from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

from briareus_playwright.browser import BrowserError, BrowserManager, BrowserTabLimitError
from briareus_playwright.tab_activity import TabPolicy
from briareus_workspace.workspace_store import WorkspaceFileStore
from playwright.async_api import BrowserContext, Page
from pydantic import ValidationError


def manager(root: Path) -> BrowserManager:
    return BrowserManager(
        workspace=WorkspaceFileStore(root / "workspace"),
        cdp_url="http://chromium:9222",
        control_url="http://chromium:9001/RPC2",
        control_token="test",
        profile_dir=root / "profile",
        executable_path="",
        headless=True,
        timeout_ms=1000,
        viewport_width=1200,
        viewport_height=800,
        max_snapshot_text_chars=1000,
        max_snapshot_elements=50,
    )


def page(url: str = "https://example.test") -> MagicMock:
    item = MagicMock(spec=Page)
    item.url = url
    item.is_closed.return_value = False
    item.title = AsyncMock(return_value="Example")

    async def close() -> None:
        item.is_closed.return_value = True

    item.close = AsyncMock(side_effect=close)
    return item


class TabPolicyContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.browser = manager(self.root)
        self.addAsyncCleanup(self.browser.stop_background_tasks)
        self.now = 0.0
        self.browser._tab_activity.clock = lambda: self.now
        self.context = MagicMock(spec=BrowserContext)
        self.context.pages = []
        self.browser._context = cast(BrowserContext, self.context)
        self.ensure = patch.object(
            self.browser, "_ensure_started", AsyncMock(return_value=self.context)
        )
        self.ensure.start()
        self.addCleanup(self.ensure.stop)

    def add_page(self, url: str = "https://example.test") -> tuple[str, MagicMock]:
        item = page(url)
        self.context.pages.append(item)
        return self.browser._register_page(cast(Page, item)), item

    async def test_idle_cleanup_protects_operators_and_inflight_operations_and_resets_on_finish(
        self,
    ) -> None:
        stale, stale_page = self.add_page()
        owned, owned_page = self.add_page()
        busy, busy_page = self.add_page()
        self.browser._operator_pages["owner"] = owned
        async with self.browser.page_operation(busy):
            self.now = 301
            self.assertEqual(await self.browser.cleanup_idle_tabs(), 1)
            stale_page.close.assert_awaited_once()
            owned_page.close.assert_not_awaited()
            busy_page.close.assert_not_awaited()
        self.assertNotIn(stale, self.browser._pages)
        self.now = 500
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
        self.now = 602
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 1)
        busy_page.close.assert_awaited_once()
        owned_page.close.assert_not_awaited()

    async def test_adoption_never_mass_closes_and_limit_rejects_new_tabs_but_reuses_settings(
        self,
    ) -> None:
        self.browser._tab_policy = TabPolicy(max_tabs=1)
        _, settings = self.add_page("chrome://settings/")
        _, existing = self.add_page()
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
        with self.assertRaises(BrowserTabLimitError) as failure:
            await self.browser._new_page(self.context)
        self.assertEqual(failure.exception.code, "browser_tab_limit")
        self.assertEqual(failure.exception.limit, 1)
        self.assertIs(await self.browser._new_page(self.context, "chrome://settings"), settings)
        existing.close.assert_not_awaited()
        self.context.new_page.assert_not_called()

    async def test_settings_and_extensions_subpages_reuse_without_navigation_or_title_wait(
        self,
    ) -> None:
        self.browser._tab_policy = TabPolicy(max_tabs=1)
        self.browser._operator_pages["owner"] = ""
        for existing_url, root_url in (
            ("chrome://settings/appearance", "chrome://settings/"),
            ("chrome://extensions/?id=example", "chrome://extensions"),
        ):
            page_id, item = self.add_page(existing_url)
            self.browser._page_titles[page_id] = "Cached title"
            for operation in (
                self.browser.open(root_url),
                self.browser.operator_new_page("owner", root_url),
            ):
                result = await operation
                self.assertEqual(result["page_id"], page_id)
                self.assertEqual(result["url"], existing_url)
                self.assertEqual(result["title"], "Cached title")
            item.goto.assert_not_called()
            self.assertEqual(item.bring_to_front.await_count, 2)
            self.browser._forget_page(page_id)
            self.context.pages.clear()
        with self.assertRaises(BrowserError):
            self.browser._operator_url("chrome://flags")
        with self.assertRaises(BrowserError):
            self.browser._operator_url("chrome://settings/appearance")

    async def test_leaving_operator_view_starts_a_fresh_idle_period(self) -> None:
        for action in ("release", "select"):
            with self.subTest(action=action):
                self.now = 0
                page_id, viewed = self.add_page()
                self.browser._operator_pages["owner"] = page_id
                self.now = 301
                self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
                if action == "release":
                    await self.browser.operator_release("owner")
                else:
                    next_id, _ = self.add_page()
                    await self.browser.operator_select_page("owner", next_id)
                self.now = 302
                self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
                viewed.close.assert_not_awaited()
                self.now = 602
                self.assertEqual(await self.browser.cleanup_idle_tabs(), 1)
                viewed.close.assert_awaited_once()

    async def test_popup_over_capacity_closes_only_the_new_popup(self) -> None:
        self.browser._tab_policy = TabPolicy(max_tabs=1)
        _, existing = self.add_page()
        popup_id, popup = self.add_page()
        await self.browser._configure_new_page(popup_id, popup)
        popup.close.assert_awaited_once()
        existing.close.assert_not_awaited()
        self.assertNotIn(popup_id, self.browser._pages)

    async def test_policy_persists_validated_values_and_disabled_idle_keeps_tabs(self) -> None:
        _, item = self.add_page()
        with patch.object(self.browser, "status", AsyncMock(return_value={"running": True})):
            await self.browser.set_tab_policy(7, False, 600)
        reloaded = manager(self.root)
        self.assertEqual(
            reloaded._tab_policy,
            TabPolicy(max_tabs=7, idle_close_enabled=False, idle_timeout_seconds=600),
        )
        self.now = 10000
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
        item.close.assert_not_awaited()
        for values in ({"max_tabs": 0}, {"max_tabs": 101}, {"idle_timeout_seconds": 29}):
            with self.assertRaises(ValidationError):
                TabPolicy.model_validate(values)

    async def test_operator_metadata_does_not_wait_for_titles_or_refresh_idle_clock(self) -> None:
        page_id, item = self.add_page()
        title_gate = asyncio.Event()
        item.title = AsyncMock(side_effect=title_gate.wait)
        self.browser._page_titles[page_id] = "Last title"
        self.now = 301
        result = await asyncio.wait_for(self.browser._operator_page_items(), timeout=0.2)
        first = result[0]
        assert isinstance(first, dict)
        self.assertEqual(first["title"], "Last title")
        self.assertTrue(self.browser._tab_activity.idle(page_id, 300))

    async def test_cancelled_operation_releases_idle_protection_and_user_events_touch_clock(
        self,
    ) -> None:
        page_id, item = self.add_page()
        await self.browser.stop_background_tasks()
        item.expose_binding = AsyncMock()
        item.add_init_script = AsyncMock()
        item.evaluate = AsyncMock()
        await self.browser._install_activity_events(page_id, item)
        callback = item.expose_binding.call_args.args[1]
        self.now = 301
        callback({})
        self.assertFalse(self.browser._tab_activity.idle(page_id, 300))
        with self.assertRaises(asyncio.CancelledError):
            async with self.browser.page_operation(page_id):
                self.now = 602
                raise asyncio.CancelledError
        self.assertFalse(self.browser._tab_activity.busy)
        self.assertFalse(self.browser._tab_activity.idle(page_id, 300))
        self.now = 903
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 1)

    async def test_close_all_and_stopped_state_do_not_restart_or_create_blank_tabs(self) -> None:
        page_id, item = self.add_page()
        self.browser._operator_pages["owner"] = page_id
        result = await self.browser.operator_close_all_pages("owner")
        self.assertEqual(result["closed_count"], 1)
        self.assertEqual(result["selected_page_id"], "")
        item.close.assert_awaited_once()
        self.context.new_page.assert_not_called()
        self.browser._manually_stopped = True
        with patch.object(self.browser, "_ensure_started", AsyncMock()) as start:
            state = await self.browser.operator_state("owner")
            self.assertFalse(state["running"])
            self.assertEqual(state["pages"], [])
            start.assert_not_called()
