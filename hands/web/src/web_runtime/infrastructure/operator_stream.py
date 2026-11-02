"""WebSocket state events and bounded CDP screencast delivery."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import dataclass, field

from playwright.async_api import CDPSession
from pydantic import ValidationError
from starlette.websockets import WebSocket

from web_runtime.domain.screencast import ScreenFrame
from web_runtime.infrastructure.operator_runtime import OperatorBrowserRuntime

from .operator_events import (
    OperatorFrameEvent,
    OperatorStateEvent,
    ScreencastFrame,
    ScreencastMetadata,
    ScreencastSession,
)


def consume_task[Result](task: asyncio.Task[Result]) -> None:
    if not task.cancelled():
        task.exception()


@dataclass
class FrameReceiver:
    session: CDPSession
    queue: asyncio.Queue[ScreenFrame] = field(default_factory=lambda: asyncio.Queue(maxsize=2))

    def receive(self, payload: object) -> None:
        try:
            envelope = ScreencastSession.model_validate(payload)
        except ValidationError:
            return
        # ACK every identified upstream frame, including invalid or dropped frames.
        task = asyncio.create_task(
            self.session.send("Page.screencastFrameAck", {"sessionId": envelope.session_id}),
        )
        task.add_done_callback(consume_task)
        try:
            frame = ScreencastFrame.model_validate(payload).to_frame()
        except ValidationError:
            return
        if self.queue.full():
            with suppress(asyncio.QueueEmpty):
                self.queue.get_nowait()
        with suppress(asyncio.QueueFull):
            self.queue.put_nowait(frame)


@dataclass
class BrowserOperatorEvents:
    browser: OperatorBrowserRuntime
    websocket: WebSocket
    task: asyncio.Task[None] | None = None

    async def state(self, owner: str) -> None:
        state = await self.browser.operator_state(owner)
        event = OperatorStateEvent.model_validate(state, from_attributes=True)
        event.type = "state"
        await self.websocket.send_text(event.model_dump_json(by_alias=True, exclude_unset=True))

    async def start_stream(self, owner: str, page: str) -> None:
        self.task = asyncio.create_task(self._stream(owner, page), name="browser-operator-stream")

    async def stop_stream(self) -> None:
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None

    async def _stream(self, owner: str, page_id: str) -> None:
        page, session = await self.browser.operator_cdp_session(owner, page_id)
        receiver = FrameReceiver(session)
        session.on("Page.screencastFrame", receiver.receive)
        try:
            await session.send(
                "Page.startScreencast",
                {
                    "format": "jpeg",
                    "quality": 72,
                    "maxWidth": self.browser.viewport_width,
                    "maxHeight": self.browser.viewport_height,
                    "everyNthFrame": 1,
                },
            )
            while True:
                frame = await receiver.queue.get()
                event = OperatorFrameEvent(
                    page_id=page_id,
                    data=frame.data,
                    metadata=ScreencastMetadata.model_validate(frame.metadata),
                    url=page.url,
                )
                await self.websocket.send_text(
                    event.model_dump_json(by_alias=True, exclude_none=True)
                )
        finally:
            with suppress(Exception):
                await session.send("Page.stopScreencast")
            with suppress(Exception):
                await session.detach()
