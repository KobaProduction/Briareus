"""Local authenticated WebSocket proxy contract, using synthetic external issuer."""

from __future__ import annotations

import asyncio
import sys
import time
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlsplit

import jwt
import uvicorn
import websockets
from fixture_server import FixtureServer
from starlette.applications import Starlette
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_oidc_parity import free_port, issuer_fixture, rust_gateway  # noqa: E402


@asynccontextmanager
async def panel_fixture() -> AsyncIterator[str]:
    async def relay(websocket: WebSocket) -> None:
        # Only fixed private routes may reach this test backend; never print tokens.
        assert websocket.headers.get("authorization", "").startswith("Bearer ")
        assert websocket.headers.get("origin") == "https://briareus.example"
        assert websocket.headers.get("cookie") is None
        assert websocket.headers.get("sec-websocket-protocol") == "briareus.v1"
        assert websocket.headers.get("x-forwarded-proto") == "https"
        assert websocket.headers.get("x-forwarded-host")
        await websocket.accept(subprotocol="briareus.v1")
        await websocket.send_text("private-upstream:" + websocket.url.path)
        try:
            while True:
                received = await websocket.receive()
                if received.get("type") == "websocket.disconnect":
                    break
                if (content := received.get("text")) is not None:
                    await websocket.send_text(content)
                elif (content := received.get("bytes")) is not None:
                    await websocket.send_bytes(content)
        except WebSocketDisconnect:
            pass

    port = free_port()
    app = Starlette(
        routes=[
            WebSocketRoute("/admin/api/realtime", relay),
            WebSocketRoute("/admin/api/browser/operator/ws", relay),
            WebSocketRoute("/admin/api/browser/cdp/page/{target_id}", relay),
        ]
    )
    server = FixtureServer(
        uvicorn.Config(
            app,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="off",
            access_log=False,
        )
    )
    task = asyncio.create_task(server.serve())
    try:
        for _ in range(150):
            if server.started:
                break
            await asyncio.sleep(0.025)
        else:
            raise RuntimeError("Control Panel WebSocket fixture unavailable")
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 6)


class WebSocketAuthorityParity(unittest.IsolatedAsyncioTestCase):
    async def test_relay_routes_forward_only_authorized_frames(self) -> None:
        async with (
            issuer_fixture() as (issuer, pem),
            panel_fixture() as panel,
            rust_gateway(issuer, "list", '["roles"]', "", panel_url=panel) as (_, endpoint),
        ):
            now = int(time.time())
            valid = jwt.encode(
                {
                    "iss": issuer,
                    "aud": "fixture-project",
                    "sub": "fixture-user",
                    "client_id": "fixture-client",
                    "exp": now + 90,
                    "iat": now - 10,
                    "roles": ["tambov"],
                },
                pem,
                algorithm="RS256",
                headers={"kid": "fixture-key-1"},
            )
            parsed = urlsplit(endpoint)
            base = "ws://briareus.example"
            transport = {"host": "127.0.0.1", "port": parsed.port, "proxy": None}
            cases = (
                ("/api/realtime", "/admin/api/realtime"),
                ("/api/browser/operator/ws", "/admin/api/browser/operator/ws"),
                ("/api/browser/cdp/page/tab-123", "/admin/api/browser/cdp/page/tab-123"),
            )
            for path, upstream in cases:
                async with websockets.connect(
                    base + path,
                    origin="https://briareus.example",
                    subprotocols=["briareus.v1", "bearer." + valid],
                    additional_headers={"Cookie": "browser-private-cookie"},
                    open_timeout=5,
                    **transport,
                ) as connection:
                    with self.subTest(path=path):
                        self.assertEqual(connection.subprotocol, "briareus.v1")
                        self.assertEqual(await connection.recv(), "private-upstream:" + upstream)
                        await connection.send("text-fixture")
                        self.assertEqual(await connection.recv(), "text-fixture")
                        await connection.send(b"\x01\x02\xff")
                        self.assertEqual(await connection.recv(), b"\x01\x02\xff")
            expiry_now = int(time.time())
            expiring = jwt.encode(
                {
                    "iss": issuer,
                    "aud": "fixture-project",
                    "sub": "fixture-user",
                    "client_id": "fixture-client",
                    "exp": expiry_now + 3,
                    "iat": expiry_now - 10,
                    "roles": ["tambov"],
                },
                pem,
                algorithm="RS256",
                headers={"kid": "fixture-key-1"},
            )
            async with websockets.connect(
                base + "/api/realtime",
                origin="https://briareus.example",
                subprotocols=["briareus.v1", "bearer." + expiring],
                open_timeout=5,
                **transport,
            ) as expiring_socket:
                self.assertIn("/admin/api/realtime", await expiring_socket.recv())
                with self.assertRaises(websockets.exceptions.ConnectionClosedError) as denial:
                    async with asyncio.timeout(7):
                        await expiring_socket.recv()
                self.assertEqual(denial.exception.code, 4401)
            for name, path, protocols, origin in (
                ("missing_bearer", "/api/realtime", ["briareus.v1"], "https://briareus.example"),
                (
                    "wrong_origin",
                    "/api/realtime",
                    ["briareus.v1", "bearer." + valid],
                    "https://attacker.example",
                ),
                (
                    "duplicate_token",
                    "/api/realtime",
                    ["briareus.v1", "bearer." + valid, "bearer.evil"],
                    "https://briareus.example",
                ),
                (
                    "invalid_route",
                    "/api/browser/cdp/page/tab+invalid",
                    ["briareus.v1", "bearer." + valid],
                    "https://briareus.example",
                ),
            ):
                with self.assertRaises(websockets.exceptions.InvalidStatus, msg=name):
                    async with websockets.connect(
                        base + path,
                        origin=origin,
                        subprotocols=protocols,
                        open_timeout=5,
                        **transport,
                    ):
                        self.fail("Invalid browser socket was accepted")


if __name__ == "__main__":
    unittest.main()
