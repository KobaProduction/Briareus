"""A bounded latest-frame stream; every Chromium frame is acknowledged."""

from __future__ import annotations

import asyncio
import contextlib

from briareus_json_values import JsonObject
from playwright.async_api import CDPSession
from starlette.websockets import WebSocket

from briareus_playwright.browser import BrowserManager

from .operator_protocol import ScreencastFrame


class _FrameQueue:
    def __init__(self, session: CDPSession) -> None:
        self.session = session
        self.frames: asyncio.Queue[ScreencastFrame] = asyncio.Queue(maxsize=2)

    def receive(self, payload: JsonObject) -> None:
        frame = ScreencastFrame.model_validate(payload)
        if frame.sessionId is not None:
            task = asyncio.create_task(
                self.session.send("Page.screencastFrameAck", {"sessionId": frame.sessionId})
            )
            task.add_done_callback(lambda item: item.exception() if not item.cancelled() else None)
        if self.frames.full():
            with contextlib.suppress(asyncio.QueueEmpty):
                self.frames.get_nowait()
        with contextlib.suppress(asyncio.QueueFull):
            self.frames.put_nowait(frame)


async def stream_operator_page(
    websocket: WebSocket, browser: BrowserManager, owner: str, page_id: str
) -> None:
    page, session = await browser.operator_cdp_session(owner, page_id)
    queue = _FrameQueue(session)
    session.on("Page.screencastFrame", queue.receive)
    try:
        await session.send(
            "Page.startScreencast",
            {
                "format": "jpeg",
                "quality": 72,
                "maxWidth": browser.viewport_width,
                "maxHeight": browser.viewport_height,
                "everyNthFrame": 1,
            },
        )
        while True:
            frame = await queue.frames.get()
            await websocket.send_json(
                {
                    "type": "frame",
                    "page_id": page_id,
                    "data": frame.data,
                    "metadata": frame.metadata,
                    "url": page.url,
                }
            )
    finally:
        with contextlib.suppress(Exception):
            async with asyncio.timeout(0.5):
                await session.send("Page.stopScreencast")
        with contextlib.suppress(Exception):
            async with asyncio.timeout(0.5):
                await session.detach()
