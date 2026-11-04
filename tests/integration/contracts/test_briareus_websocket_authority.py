from __future__ import annotations

import asyncio
import threading
import unittest
from collections.abc import AsyncIterator, Callable, Mapping
from typing import cast

from briareus_support import TokenAuthorityHarness
from briareus_websocket_transport.websocket_proxy import _relay_pair
from control_panel_api.presentation.identity_websocket import relay_authenticated_socket
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.testclient import TestClient
from starlette.websockets import WebSocket, WebSocketDisconnect
from websockets.asyncio.client import ClientConnection


class UpstreamChannel:
    def __init__(self) -> None:
        self.received: list[str | bytes] = []
        self.outgoing: asyncio.Queue[str | bytes] = asyncio.Queue()

    async def send(self, message: str | bytes) -> None:
        self.received.append(message)
        await self.outgoing.put(message)

    async def push(self, message: str) -> None:
        await self.outgoing.put(message)

    def __aiter__(self) -> AsyncIterator[str | bytes]:
        return self

    async def __anext__(self) -> str | bytes:
        return await self.outgoing.get()


class SocketRelay:
    def __init__(self, upstream: UpstreamChannel) -> None:
        self.upstream = upstream

    async def __call__(
        self,
        websocket: WebSocket,
        target_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        origin: str | None = None,
        accept_downstream: bool = True,
        is_active: Callable[[], bool] | None = None,
    ) -> None:
        del target_url, headers, origin
        if accept_downstream:
            await websocket.accept()
        await _relay_pair(websocket, cast(ClientConnection, self.upstream), is_active)


class OngoingWebSocketAuthorityContracts(unittest.TestCase):
    def setUp(self) -> None:
        self.harness = TokenAuthorityHarness()
        self.addCleanup(self.harness.close)
        self.token = self.harness.authenticate()
        self.principal = self.harness.identity.verify(self.token)
        self.upstream = UpstreamChannel()
        self.endpoint_finished = threading.Event()
        self.relay_completed = False

        async def endpoint(websocket: WebSocket) -> None:
            try:
                await relay_authenticated_socket(
                    websocket,
                    "wss://unused.example.test",
                    principal=self.principal,
                    headers={},
                    relay=SocketRelay(self.upstream),
                )
                self.relay_completed = True
            finally:
                self.endpoint_finished.set()

        self.app = Starlette(routes=[WebSocketRoute("/socket", endpoint)])

    def test_active_token_relays_both_directions(self) -> None:
        with TestClient(self.app) as client, client.websocket_connect("/socket") as socket:
            socket.send_text("client-command")
            self.assertEqual(socket.receive_text(), "client-command")
            assert client.portal is not None
            client.portal.call(self.upstream.push, "upstream-event")
            self.assertEqual(socket.receive_text(), "upstream-event")
            self.assertEqual(self.upstream.received, ["client-command"])
            socket.close()
            self.assertTrue(self.endpoint_finished.wait(timeout=5))
            self.assertTrue(self.relay_completed)

    def test_expiry_prevents_a_new_client_effect_on_an_already_open_socket(self) -> None:
        with TestClient(self.app) as client, client.websocket_connect("/socket") as socket:
            self.harness.expire()
            socket.send_text("must-not-run")
            with self.assertRaises(WebSocketDisconnect) as failure:
                socket.receive_text()
            self.assertEqual(failure.exception.code, 4401)
            self.assertEqual(self.upstream.received, [])

    def test_expiry_prevents_an_upstream_event_from_leaking_to_an_open_socket(self) -> None:
        with TestClient(self.app) as client, client.websocket_connect("/socket") as socket:
            self.harness.expire()
            assert client.portal is not None
            client.portal.call(self.upstream.push, "must-not-leak")
            with self.assertRaises(WebSocketDisconnect) as failure:
                socket.receive_text()
            self.assertEqual(failure.exception.code, 4401)

    def test_an_idle_socket_is_closed_when_its_external_token_expires(self) -> None:
        with TestClient(self.app) as client, client.websocket_connect("/socket") as socket:
            self.harness.expire()
            with self.assertRaises(WebSocketDisconnect) as failure:
                socket.receive_text()
            self.assertEqual(failure.exception.code, 4401)
            self.assertEqual(self.upstream.received, [])
