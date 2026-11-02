"""Human preview captures the current surface, independent of font readiness."""

import base64
import unittest
from unittest.mock import AsyncMock, Mock

from playwright.async_api import CDPSession, Page

from web_runtime.infrastructure.viewport_capture import capture_viewport


class ViewportCaptureTests(unittest.IsolatedAsyncioTestCase):
    def page(self) -> tuple[Mock, Mock]:
        page = Mock(spec=Page)
        session = Mock(spec=CDPSession)
        page.context.new_cdp_session = AsyncMock(return_value=session)
        page.evaluate = AsyncMock(
            return_value={"x": 0, "y": 120, "width": 1280, "height": 720, "pixel_ratio": 2}
        )
        page.screenshot = AsyncMock(side_effect=AssertionError("Font-waiting capture forbidden"))
        session.send = AsyncMock(return_value={"data": base64.b64encode(b"frame").decode()})
        session.detach = AsyncMock()
        return page, session

    async def test_current_surface_uses_css_pixels_without_playwright_font_wait(self) -> None:
        page, session = self.page()
        self.assertEqual(await capture_viewport(page), base64.b64encode(b"frame").decode())
        page.screenshot.assert_not_awaited()
        session.send.assert_awaited_once_with(
            "Page.captureScreenshot",
            {
                "format": "png",
                "fromSurface": True,
                "captureBeyondViewport": False,
                "clip": {"x": 0.0, "y": 120.0, "width": 1280.0, "height": 720.0, "scale": 0.5},
            },
        )
        session.detach.assert_awaited_once()

    async def test_failed_capture_detaches_session_without_retry(self) -> None:
        page, session = self.page()
        session.send.side_effect = RuntimeError("Compositor unavailable")
        with self.assertRaises(RuntimeError):
            await capture_viewport(page)
        session.send.assert_awaited_once()
        session.detach.assert_awaited_once()

    async def test_oversized_surface_is_rejected_before_transport(self) -> None:
        page, session = self.page()
        session.send.return_value = {"data": base64.b64encode(b"x" * 256001).decode()}
        with self.assertRaisesRegex(ValueError, "transport limit"):
            await capture_viewport(page)
        session.detach.assert_awaited_once()
