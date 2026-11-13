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
        self.ensure_mock = self.ensure.start()
        self.addCleanup(self.ensure.stop)
        self.target_lookup = patch.object(
            self.browser, "_target_id", AsyncMock(side_effect=lambda tab: f"target-{id(tab)}")
        )
        self.target_lookup.start()
        self.addCleanup(self.target_lookup.stop)

    async def add_page(self, url: str = "https://example.test") -> tuple[str, MagicMock]:
        item = page(url)
        self.context.pages.append(item)
        return await self.browser._register_page(cast(Page, item)), item

    async def test_surviving_target_keeps_id_and_gets_fresh_idle_budget_on_reattach(
        self,
    ) -> None:
        target_id, existing = await self.add_page()
        self.now = 1000
        replacement = manager(self.root)
        replacement._tab_activity.clock = lambda: self.now
        with patch.object(
            replacement, "_target_id", AsyncMock(return_value=target_id)
        ):
            adopted_id = await replacement._register_page(cast(Page, existing))
        self.assertEqual(adopted_id, target_id)
        self.assertEqual(replacement._pages[target_id], existing)
        replacement._context = cast(BrowserContext, self.context)
        with patch.object(replacement, "_ensure_started", AsyncMock(return_value=self.context)):
            self.assertEqual(await replacement.cleanup_idle_tabs(), 0)
        self.now = 1299
        with patch.object(replacement, "_ensure_started", AsyncMock(return_value=self.context)):
            self.assertEqual(await replacement.cleanup_idle_tabs(), 0)
            self.now = 1301
            self.assertEqual(await replacement.cleanup_idle_tabs(), 1)
        existing.close.assert_awaited_once()
        await replacement.stop_background_tasks()

    async def test_idle_timer_adopts_existing_browser_tabs_without_agent_calls(self) -> None:
        page_id, existing = await self.add_page()
        self.ensure_mock.reset_mock()
        self.now = 100
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
        self.ensure_mock.assert_awaited_once()
        self.assertIn(page_id, self.browser._pages)
        existing.close.assert_not_awaited()

    async def test_disabled_or_stopped_timer_never_reconnects_chromium(self) -> None:
        self.browser._tab_policy = TabPolicy(idle_close_enabled=False)
        self.ensure_mock.reset_mock()
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
        self.ensure_mock.assert_not_awaited()
        self.browser._tab_policy = TabPolicy()
        self.browser._manually_stopped = True
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
        self.ensure_mock.assert_not_awaited()

    async def test_idle_cycle_discovers_chromium_pages_after_mcp_restart(self) -> None:
        existing = page("https://persistent.example.test")
        target_id = "CHROME_TARGET_123"
        fake_context = MagicMock(spec=BrowserContext)
        fake_context.pages = [existing]
        fake_context.cookies = AsyncMock(return_value=[])
        cdp = MagicMock()
        cdp.send = AsyncMock(return_value={"targetInfo": {"targetId": target_id}})
        cdp.detach = AsyncMock()
        fake_context.new_cdp_session = AsyncMock(return_value=cdp)
        chrome = MagicMock()
        chrome.contexts = [fake_context]
        chrome.is_connected.return_value = True
        driver = MagicMock()
        driver.chromium.connect_over_cdp = AsyncMock(return_value=chrome)
        playwright = MagicMock()
        playwright.start = AsyncMock(return_value=driver)
        restarted = manager(self.root)
        restarted._tab_activity.clock = lambda: self.now
        control = MagicMock()
        control.command = AsyncMock(return_value=MagicMock(manually_stopped=False))
        restarted._control = control
        with (
            patch("playwright.async_api.async_playwright", return_value=playwright),
            patch.object(restarted, "_set_chromium_developer_state", AsyncMock()),
            patch.object(restarted, "_apply_color_scheme", AsyncMock()),
        ):
            self.assertEqual(await restarted.cleanup_idle_tabs(), 0)
        self.assertEqual(list(restarted._pages), [target_id])
        self.assertIs(restarted._pages[target_id], existing)
        self.assertEqual(restarted._tab_activity.last_used[target_id], self.now)
        self.now = 299
        self.assertEqual(await restarted.cleanup_idle_tabs(), 0)
        self.now = 301
        self.assertEqual(await restarted.cleanup_idle_tabs(), 1)
        existing.close.assert_awaited_once()
        await restarted.stop_background_tasks()

    async def test_late_previous_wrapper_close_cannot_remove_reattached_target(self) -> None:
        original = page()
        replacement = page()
        fixed_target = "CHROME_TARGET_REATTACHED"
        with patch.object(self.browser, "_target_id", AsyncMock(return_value=fixed_target)):
            await self.browser._register_page(cast(Page, original))
            await self.browser._register_page(cast(Page, replacement))
        self.assertIs(self.browser._pages[fixed_target], replacement)
        self.browser._forget_page(fixed_target, cast(Page, original))
        self.assertIs(self.browser._pages[fixed_target], replacement)

    async def test_persisted_target_access_restriction_survives_mcp_restart(self) -> None:
        target_id = "CHROME_LOCKED_TARGET"
        self.browser._blocked_target_ids.add(target_id)
        self.browser._persist_policy()
        restarted = manager(self.root)
        existing = page()
        with patch.object(restarted, "_target_id", AsyncMock(return_value=target_id)):
            self.assertEqual(await restarted._register_page(cast(Page, existing)), target_id)
        self.assertFalse(restarted._agent_access_allowed(target_id))
        with self.assertRaisesRegex(BrowserError, "locked by operator"):
            await restarted.snapshot(target_id)
        await restarted.stop_background_tasks()

    async def test_registration_never_invents_a_target_if_cdp_lookup_fails(self) -> None:
        existing = page()
        with (
            patch.object(
                self.browser, "_target_id", AsyncMock(side_effect=RuntimeError("CDP unavailable"))
            ),
            self.assertRaisesRegex(RuntimeError, "CDP unavailable"),
        ):
            await self.browser._register_page(cast(Page, existing))
        self.assertFalse(self.browser._pages)
        self.assertFalse(self.browser._page_ids)

    async def test_state_waits_for_restart_and_does_not_reopen_a_closed_context(self) -> None:
        self.browser._operator_pages["owner"] = ""
        async with self.browser._reset_lock:
            with patch.object(
                self.browser, "_operator_page_items", AsyncMock(return_value=[])
            ) as items:
                task = asyncio.create_task(self.browser.operator_state("owner"))
                await asyncio.sleep(0)
                items.assert_not_awaited()
        state = await task
        self.assertEqual(state["pages"], [])

    async def test_start_page_replaces_only_empty_sessions_and_new_tabs_have_homepage(self) -> None:
        _, blank = await self.add_page("about:blank")
        blank.goto = AsyncMock()
        await self.browser._prepare_operator_start()
        blank.goto.assert_awaited_once_with("chrome://newtab/", wait_until="domcontentloaded")
        blank.goto.reset_mock()
        await self.add_page("https://example.test/keep")
        await self.browser._prepare_operator_start()
        blank.goto.assert_not_awaited()

    async def test_idle_cleanup_protects_operators_and_inflight_operations_and_resets_on_finish(
        self,
    ) -> None:
        stale, stale_page = await self.add_page()
        owned, owned_page = await self.add_page()
        busy, busy_page = await self.add_page()
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

    async def test_missing_tab_explains_possible_idle_cleanup_when_enabled(self) -> None:
        page_id, tab = await self.add_page()
        self.now = 301
        self.assertEqual(await self.browser.cleanup_idle_tabs(), 1)
        tab.close.assert_awaited_once()
        for operation in (
            self.browser.snapshot(page_id),
            self.browser.open("https://example.test", page_id),
            self.browser.click(page_id, "e1"),
        ):
            with self.assertRaises(BrowserError) as failure:
                await operation
            message = str(failure.exception)
            self.assertIn("browser page not found", message)
            self.assertIn("may have been closed", message)
            self.assertIn("300 seconds", message)
            self.assertIn("browser_pages", message)
            self.assertIn("browser_open", message)
            self.assertIn("new page_id", message)
            self.assertNotIn("was automatically closed", message)

    async def test_missing_tab_uses_current_configured_timeout_not_default(self) -> None:
        self.browser._tab_policy = TabPolicy(idle_timeout_seconds=600)
        with self.assertRaises(BrowserError) as failure:
            await self.browser.snapshot("page-not-known")
        message = str(failure.exception)
        self.assertIn("600 seconds", message)
        self.assertNotIn("300 seconds", message)
        self.assertIn("Chromium, Playwright, or the server", message)

    async def test_missing_tab_with_idle_cleanup_disabled_does_not_suggest_timeout(self) -> None:
        self.browser._tab_policy = TabPolicy(idle_close_enabled=False)
        page_id, tab = await self.add_page()
        await self.browser.close_page(page_id)
        tab.close.assert_awaited_once()
        for missing_id in (page_id, "page-after-restart"):
            with self.assertRaises(BrowserError) as failure:
                await self.browser.snapshot(missing_id)
            message = str(failure.exception)
            self.assertIn("another agent or user", message)
            self.assertIn("may have restarted", message)
            self.assertIn("browser_open", message)
            self.assertNotIn("idle", message)
            self.assertNotIn("seconds", message)

    async def test_unknown_tab_when_idle_enabled_does_not_claim_actual_cause(self) -> None:
        with self.assertRaises(BrowserError) as failure:
            await self.browser.snapshot("page-never-existed")
        message = str(failure.exception)
        self.assertIn("may have been closed", message)
        self.assertIn("may be closed after 300 seconds", message)
        self.assertNotIn("was automatically closed", message)

    async def test_adoption_never_mass_closes_and_limit_rejects_new_tabs_but_reuses_settings(
        self,
    ) -> None:
        self.browser._tab_policy = TabPolicy(max_tabs=1)
        _, settings = await self.add_page("chrome://settings/")
        _, existing = await self.add_page()
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
            page_id, item = await self.add_page(existing_url)
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
                page_id, viewed = await self.add_page()
                self.browser._operator_pages["owner"] = page_id
                self.now = 301
                self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
                if action == "release":
                    await self.browser.operator_release("owner")
                else:
                    next_id, _ = await self.add_page()
                    await self.browser.operator_select_page("owner", next_id)
                self.now = 302
                self.assertEqual(await self.browser.cleanup_idle_tabs(), 0)
                viewed.close.assert_not_awaited()
                self.now = 602
                self.assertEqual(await self.browser.cleanup_idle_tabs(), 1)
                viewed.close.assert_awaited_once()

    async def test_popup_over_capacity_closes_only_the_new_popup(self) -> None:
        self.browser._tab_policy = TabPolicy(max_tabs=1)
        _, existing = await self.add_page()
        popup_id, popup = await self.add_page()
        await self.browser._configure_new_page(popup_id, popup)
        popup.close.assert_awaited_once()
        existing.close.assert_not_awaited()
        self.assertNotIn(popup_id, self.browser._pages)

    async def test_policy_persists_validated_values_and_disabled_idle_keeps_tabs(self) -> None:
        _, item = await self.add_page()
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
        page_id, item = await self.add_page()
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
        page_id, item = await self.add_page()
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
        page_id, item = await self.add_page()
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
