"""Capture the current Chromium surface without waiting for document font readiness."""

import base64

from playwright.async_api import Page
from pydantic import BaseModel, ConfigDict, Field


class ViewportGeometry(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", allow_inf_nan=False)
    x: float
    y: float
    width: float = Field(gt=0, le=7680)
    height: float = Field(gt=0, le=4320)
    pixel_ratio: float = Field(gt=0)


class ViewportCapture(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    data: str = Field(max_length=341336)


async def capture_viewport(page: Page) -> str:
    session = await page.context.new_cdp_session(page)
    try:
        # A human preview shows the current compositor frame. Playwright screenshot
        # waits for document.fonts.ready, which can stall while Chromium settings
        # loads fonts. Native input must not wait for those network resources.
        geometry = ViewportGeometry.model_validate(
            await page.evaluate(
                """() => ({x: scrollX, y: scrollY, width: innerWidth,
                           height: innerHeight, pixel_ratio: devicePixelRatio})"""
            )
        )
        frame = ViewportCapture.model_validate(
            await session.send(
                "Page.captureScreenshot",
                {
                    "format": "png",
                    "fromSurface": True,
                    "captureBeyondViewport": False,
                    "clip": {
                        "x": geometry.x,
                        "y": geometry.y,
                        "width": geometry.width,
                        "height": geometry.height,
                        "scale": 1 / geometry.pixel_ratio,
                    },
                },
            )
        )
        if len(base64.b64decode(frame.data, validate=True)) > 256000:
            raise ValueError("Viewport preview exceeds transport limit; use a smaller viewport")
        return frame.data
    finally:
        await session.detach()
