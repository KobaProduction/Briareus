"""CDP frames are ACKed before queue eviction and cancellation detaches the session."""

import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, call, patch

from playwright.async_api import CDPSession
from starlette.websockets import WebSocket

from modules.web.browser import BrowserManager
from modules.web.infrastructure.operator_stream import BrowserOperatorEvents, FrameReceiver


class OperatorStreamTests(unittest.IsolatedAsyncioTestCase):
    async def test_every_frame_is_acked_even_when_bounded_queue_drops_oldest(self) -> None:
        session = Mock(spec=CDPSession, send=AsyncMock())
        receiver = FrameReceiver(session)
        for sequence in range(3):
            receiver.receive(
                {
                    "sessionId": sequence,
                    "data": str(sequence),
                    "metadata": {
                        "offsetTop": 0,
                        "pageScaleFactor": 1,
                        "deviceWidth": 1280,
                        "deviceHeight": 720,
                        "scrollOffsetX": 0,
                        "scrollOffsetY": 0,
                    },
                }
            )
        await asyncio.sleep(0)
        self.assertEqual(
            session.send.await_args_list,
            [call("Page.screencastFrameAck", {"sessionId": sequence}) for sequence in range(3)],
        )
        self.assertEqual(receiver.queue.qsize(), 2)
        self.assertEqual((await receiver.queue.get()).data, "1")
        self.assertEqual((await receiver.queue.get()).data, "2")

    async def test_cancel_stops_screencast_and_detaches_before_replacement(self) -> None:
        browser = BrowserManager.__new__(BrowserManager)
        browser.viewport_width = 1280
        browser.viewport_height = 720
        session = Mock(spec=CDPSession, send=AsyncMock(), detach=AsyncMock())
        events = BrowserOperatorEvents(browser, Mock(spec=WebSocket))
        with patch.object(
            BrowserManager,
            "operator_cdp_session",
            new=AsyncMock(return_value=(Mock(url="about:blank"), session)),
        ):
            await events.start_stream("owner", "page")
            task = events.task
            await asyncio.sleep(0)
            await events.stop_stream()
        self.assertIsNone(events.task)
        self.assertIsNotNone(task)
        if task is not None:
            self.assertTrue(task.cancelled())
        self.assertEqual(session.send.await_args_list[-1], call("Page.stopScreencast"))
        session.detach.assert_awaited_once()
