"""Canonical native page allocation and operator profile reset lifecycle."""

from __future__ import annotations

import asyncio
import shutil
from typing import TYPE_CHECKING

from web_runtime.browser_models import CleanBrowserResult, PageSummary

from .browser_errors import BrowserError

if TYPE_CHECKING:
    from .browser_operations import BrowserOperations


async def navigate_page(browser: BrowserOperations, url: str, page_id: str = "") -> PageSummary:
    context = await browser._ensure_started()
    target_url = "about:blank" if url == "about:blank" and not page_id else browser._url(url)
    browser._require_agent_access(page_id)
    if page_id:
        page = await browser._page(page_id)
    else:
        browser._require_tab_capacity()
        page = await context.new_page()
        page_id = browser._register_page(page)
    response = await page.goto(target_url, wait_until="domcontentloaded")
    result = await browser._summary(page_id, page)
    result.http_status = response.status if response is not None else None
    return result


async def create_operator_page(
    browser: BrowserOperations, owner_token: str, url: str = ""
) -> PageSummary:
    browser._require_operator(owner_token)
    context = await browser._ensure_started()
    browser._require_tab_capacity()
    page = await context.new_page()
    page_id = browser._register_page(page)
    if url.strip():
        await page.goto(browser._operator_url(url), wait_until="domcontentloaded")
    async with browser._operator_lock:
        browser._operator_pages[owner_token] = page_id
    return await browser._summary(page_id, page)


async def clean_operator_browser(
    browser: BrowserOperations, owner_token: str
) -> CleanBrowserResult:
    browser._require_operator(owner_token)
    async with browser._reset_lock:
        # Block agents before destroying the credential-bearing profile.
        async with browser._policy_lock:
            browser._policy.agent_access_enabled = False
            browser._policy.developer_access_enabled = False
        await browser._notify_privileged_access()

        await browser._notify_restart()
        browser._developer_backend_connected = False
        await browser._stop_runtime(stop_display=True)
        browser._extension_registry.clear()
        await asyncio.to_thread(shutil.rmtree, browser.profile_dir, True)
        state_root = browser.profile_dir.parent
        for name in ("cache", "config", "crash"):
            await asyncio.to_thread(shutil.rmtree, state_root / name, True)
        browser.profile_dir.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(browser._persist_policy)

        async with browser._start_lock:
            await browser._start_locked()
        context = browser._context
        if context is None:
            raise BrowserError("browser failed to restart after clean")
        page_items: list[PageSummary] = []
        for page in list(context.pages):
            if page.is_closed():
                continue
            page_id = browser._register_page(page)
            page_items.append(await browser._summary(page_id, page))
        if not page_items:
            browser._require_tab_capacity()
            page = await context.new_page()
            page_id = browser._register_page(page)
            page_items = [await browser._summary(page_id, page)]
        first_page = page_items[0] if page_items else None
        selected_page_id = first_page.page_id if first_page is not None else ""
        async with browser._operator_lock:
            for token in list(browser._operator_pages):
                browser._operator_pages[token] = selected_page_id
        return CleanBrowserResult(
            cleaned=True,
            agent_access_enabled=False,
            developer_access_enabled=False,
            developer_access_effective=False,
            selected_page_id=selected_page_id,
            page_count=len(page_items),
        )
