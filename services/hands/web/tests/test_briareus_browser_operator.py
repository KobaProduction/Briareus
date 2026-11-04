from __future__ import annotations

import asyncio
import unittest
from typing import cast
from unittest.mock import AsyncMock, MagicMock

from briareus_web.browser import BrowserError, BrowserManager
from briareus_web.developer_sync import DeveloperSyncResult
from briareus_web.operator import _OperatorSession, browser_operator_websocket
from briareus_web.operator_protocol import AccessCommand, MouseCommand, parse_command
from briareus_web.operator_stream import _FrameQueue
from playwright.async_api import CDPSession
from starlette.websockets import WebSocket


class OperatorProtocolContracts(unittest.TestCase):
    def test_commands_are_discriminated_and_permissions_require_booleans(self) -> None:
        self.assertIsInstance(parse_command('{"type":"mouse","x":12,"y":3}'), MouseCommand)
        self.assertIsInstance(
            parse_command('{"type":"set_agent_access","allowed":false}'), AccessCommand
        )
        for allowed in ('"false"', "0", "null"):
            with self.subTest(allowed=allowed), self.assertRaises(ValueError):
                parse_command('{"type":"set_agent_access","allowed":' + allowed + "}")
        self.assertIsNone(parse_command('{"type":"future_command"}'))
        self.assertIsNone(parse_command("[]"))
        with self.assertRaisesRegex(ValueError, "invalid JSON"):
            parse_command("{")

    def test_developer_result_preserves_extension_flags_and_failure_details(self) -> None:
        result = DeveloperSyncResult.model_validate(
            {
                "inDeveloperMode": False,
                "eligibleExtensionIds": ["first", "second"],
                "extensions": [
                    {"id": "first", "userScriptsAccess": False, "ok": True},
                    {"id": "second", "userScriptsAccess": False, "ok": False, "error": "denied"},
                ],
            }
        )
        self.assertEqual(result.failure_details(), "second: denied")
        self.assertEqual(
            result.response(False)["extensions"],
            [
                {"id": "first", "userScriptsAccess": False, "ok": True},
                {"id": "second", "userScriptsAccess": False, "ok": False, "error": "denied"},
            ],
        )


class OperatorLifecycleContracts(unittest.IsolatedAsyncioTestCase):
    async def test_input_cannot_escape_selected_page(self) -> None:
        browser = MagicMock(spec=BrowserManager)
        session = _OperatorSession(MagicMock(), cast(BrowserManager, browser), "owner", "active")
        command = parse_command('{"type":"key","page_id":"another","key":"Enter"}')
        assert command is not None
        with self.assertRaisesRegex(BrowserError, "target is not active"):
            await session.dispatch(command)
        browser.operator_key.assert_not_called()
        self.assertEqual(session.input_page_id(""), "active")

    async def test_every_frame_is_acknowledged_while_backpressure_drops_old_frames(self) -> None:
        cdp = MagicMock(spec=CDPSession)
        cdp.send = AsyncMock()
        queue = _FrameQueue(cast(CDPSession, cdp))
        for index in range(5):
            queue.receive(
                {"sessionId": index, "data": str(index), "metadata": {"timestamp": index}}
            )
        await asyncio.sleep(0)
        self.assertEqual(cdp.send.await_count, 5)
        self.assertEqual((await queue.frames.get()).data, "3")
        self.assertEqual((await queue.frames.get()).data, "4")
        self.assertTrue(queue.frames.empty())

    async def test_release_always_stops_stream_and_releases_owner(self) -> None:
        websocket = MagicMock(spec=WebSocket)
        websocket.headers = {"authorization": "Bearer secret"}
        websocket.accept = AsyncMock()
        websocket.close = AsyncMock()
        websocket.send_json = AsyncMock()
        websocket.receive_text = AsyncMock(return_value='{"type":"release"}')
        browser = MagicMock(spec=BrowserManager)
        browser.operator_acquire = AsyncMock(return_value={"owner_token": "owner"})
        browser.operator_state = AsyncMock(return_value={"selected_page_id": ""})
        browser.operator_release = AsyncMock()
        await browser_operator_websocket(
            cast(WebSocket, websocket),
            browser=cast(BrowserManager, browser),
            service_token="secret",
        )
        browser.operator_release.assert_awaited_once_with("owner")
        websocket.close.assert_awaited_once()

    async def test_invalid_token_does_not_acquire_browser_owner(self) -> None:
        websocket = MagicMock(spec=WebSocket)
        websocket.headers = {"authorization": "Bearer wrong"}
        websocket.close = AsyncMock()
        browser = MagicMock(spec=BrowserManager)
        await browser_operator_websocket(
            cast(WebSocket, websocket),
            browser=cast(BrowserManager, browser),
            service_token="secret",
        )
        browser.operator_acquire.assert_not_called()
        websocket.close.assert_awaited_once_with(code=4401)
