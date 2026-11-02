"""Exercise the real operator transport with isolated provider mocks."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect

from modules.web.browser import BrowserError, BrowserManager
from modules.web.operator import browser_operator_websocket
from web_runtime.browser_models import Capabilities, Dimensions, OperatorLease, OperatorState


class OperatorWebsocketTests(unittest.TestCase):
    def setUp(self) -> None:
        self.service_token = uuid4().hex
        self.owner = uuid4().hex
        self.browser = object.__new__(BrowserManager)
        self.acquire = AsyncMock(
            return_value=OperatorLease(owner_token=self.owner, selected_page_id="")
        )
        self.state = AsyncMock(
            return_value=OperatorState(
                control="owner",
                selected_page_id="",
                pages=[],
                page_count=0,
                operator_count=1,
                agent_access_enabled=True,
                developer_access_enabled=False,
                developer_access_effective=False,
                developer_backend="chromium",
                can_reopen_closed_tab=False,
                capabilities=Capabilities(set_viewport=True, set_theme=True, remote_devtools=False),
                color_scheme="dark",
                viewport=Dimensions(width=1280, height=720),
                screen=Dimensions(width=1280, height=720),
            )
        )
        self.release = AsyncMock()
        self.access = AsyncMock()
        self.mouse = AsyncMock()
        for name, mock in (
            ("operator_acquire", self.acquire),
            ("operator_state", self.state),
            ("operator_release", self.release),
            ("operator_set_agent_access", self.access),
            ("operator_mouse", self.mouse),
        ):
            patcher = patch.object(BrowserManager, name, new=mock)
            patcher.start()
            self.addCleanup(patcher.stop)

        async def route(websocket: WebSocket) -> None:
            await browser_operator_websocket(
                websocket, browser=self.browser, service_token=self.service_token
            )

        self.app = Starlette(routes=[WebSocketRoute("/operator", route)])

    def test_authorized_protocol_errors_permissions_and_owner_release(self) -> None:
        with (
            TestClient(self.app) as client,
            client.websocket_connect(
                "/operator",
                headers={"authorization": f"Bearer {self.service_token}"},
            ) as socket,
        ):
            self.assertEqual(socket.receive_json()["type"], "state")
            socket.send_text("{")
            self.assertEqual(socket.receive_json(), {"type": "error", "message": "invalid JSON"})
            socket.send_json({"type": "mouse", "page_id": "foreign"})
            self.assertEqual(socket.receive_json()["type"], "error")
            socket.send_json({"type": "set_agent_access", "allowed": "yes"})
            self.assertEqual(
                socket.receive_json(),
                {
                    "type": "error",
                    "message": "invalid operator command",
                },
            )
            self.access.assert_not_awaited()
            socket.send_json({"type": "set_agent_access", "allowed": False})
            self.assertEqual(socket.receive_json()["type"], "state")
            socket.send_json({"type": "release"})
            self.assertEqual(socket.receive()["type"], "websocket.close")
        self.access.assert_awaited_once_with(self.owner, False)
        self.mouse.assert_not_awaited()
        self.release.assert_awaited_once_with(self.owner)

    def test_auth_rejection_never_acquires_browser(self) -> None:
        with (
            TestClient(self.app) as client,
            self.assertRaises(WebSocketDisconnect) as caught,
            client.websocket_connect("/operator"),
        ):
            self.fail("Missing token accepted")
        self.assertEqual(caught.exception.code, 4401)
        self.acquire.assert_not_awaited()

    def test_acquire_conflict_reports_error_and_retains_close_code(self) -> None:
        self.acquire.side_effect = BrowserError("busy")
        with (
            TestClient(self.app) as client,
            client.websocket_connect(
                "/operator",
                headers={"authorization": f"Bearer {self.service_token}"},
            ) as socket,
        ):
            self.assertEqual(socket.receive_json(), {"type": "error", "message": "busy"})
            self.assertEqual(socket.receive()["code"], 4409)
        self.release.assert_not_awaited()
