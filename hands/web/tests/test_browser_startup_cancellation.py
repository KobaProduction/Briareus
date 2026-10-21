"""A cancelled startup must not leave an untracked live display server."""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from modules.web.browser import BrowserManager


class DisplayStartupCancellationTests(unittest.IsolatedAsyncioTestCase):
    async def test_cancel_during_display_start_terminates_tracked_process(self):
        browser = object.__new__(BrowserManager)
        browser.headless = False
        browser.display = ":99"
        browser.xvfb_enabled = True
        browser.screen_width, browser.screen_height, browser.color_depth = 1280, 720, 24
        browser._display_process = None
        browser._browser_subprocess_environment = lambda: {}
        browser._terminate_display_process = AsyncMock()
        process = AsyncMock()
        process.returncode = None
        with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)), \
             patch("asyncio.sleep", AsyncMock(side_effect=asyncio.CancelledError)):
            with self.assertRaises(asyncio.CancelledError):
                await browser._ensure_display_locked()
        browser._terminate_display_process.assert_awaited_once_with(process)
        self.assertIsNone(browser._display_process)
