"""Isolated Python-vs-Rust Gateway HTTP proxy contract: no production network."""

from __future__ import annotations

import asyncio
import socket
import sys
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

import httpx
import uvicorn
from fixture_server import FixtureServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/gateway/src"))
from gateway.reverse_proxy import ReverseProxy  # noqa: E402

BINARY = ROOT / "services/gateway-rust/target/debug/briareus-gateway-rust"


def allocated_socket() -> socket.socket:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(100)
    sock.setblocking(False)
    return sock


@asynccontextmanager
async def fixture_backend() -> AsyncIterator[str]:
    listener = allocated_socket()
    port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"

    async def response(request: Request) -> Response:
        if request.url.path.endswith("/redirect"):
            next_url = origin + "/admin/api/welcome"
            return Response(
                status_code=302,
                headers={
                    "location": origin + "/admin/api/next?callback=" + quote(next_url, safe="")
                },
            )
        if request.url.path.endswith("/cookies"):
            answer = PlainTextResponse("cookie")
            answer.headers.append("set-cookie", "a=1; Path=/")
            answer.headers.append("set-cookie", "b=2; Path=/")
            return answer
        body = await request.body()
        return JSONResponse(
            {
                "method": request.method,
                "path": request.url.path,
                "query": request.url.query,
                "host": request.headers.get("host"),
                "forwarded_host": request.headers.get("x-forwarded-host"),
                "forwarded_proto": request.headers.get("x-forwarded-proto"),
                "cookie": request.headers.get("cookie"),
                "body": body.decode("utf-8"),
            }
        )

    app = Starlette(
        routes=[
            Route(
                "/{path:path}",
                response,
                methods=[
                    "GET",
                    "HEAD",
                    "POST",
                    "PUT",
                    "PATCH",
                    "DELETE",
                    "OPTIONS",
                ],
            )
        ]
    )
    config = uvicorn.Config(app, log_level="error", lifespan="off", access_log=False)
    server = FixtureServer(config)
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        for _ in range(150):
            if server.started:
                break
            await asyncio.sleep(0.02)
        else:
            raise RuntimeError("fixture backend startup failed")
        yield origin
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 6)
        listener.close()


class GatewayHttpParity(unittest.IsolatedAsyncioTestCase):
    async def test_public_http_proxy_contract(self) -> None:
        async with fixture_backend() as backend:
            api = ReverseProxy(
                backend,
                backend_name="management",
                public_prefix="/api",
                upstream_prefix="/admin/api",
            )
            ui = ReverseProxy(backend, backend_name="management-ui", public_prefix="/admin")

            # Synthetic Python Gateway with identical route priority to production.
            async def removed(_: Request) -> Response:
                return PlainTextResponse("Not Found", status_code=404)

            python_app = Starlette(
                routes=[
                    Route("/admin/api", removed),
                    Route("/admin/api/{path:path}", removed),
                    Route("/api", api.handle, methods=["GET", "POST", "PUT"]),
                    Route("/api/{path:path}", api.handle, methods=["GET", "POST", "PUT"]),
                    Route("/admin", ui.handle, methods=["GET", "POST"]),
                    Route("/admin/{path:path}", ui.handle, methods=["GET", "POST"]),
                ]
            )
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=python_app),
                base_url="http://localhost:18080",
                trust_env=False,
            ) as python:
                rust_listener = allocated_socket()
                rust_port = rust_listener.getsockname()[1]
                rust_listener.close()
                env = {
                    "RUST_GATEWAY_SHADOW_ONLY": "true",
                    "BIND_HOST": "127.0.0.1",
                    "PORT": str(rust_port),
                    "BRIAREUS_NODE_ID": "fixture-node",
                    "BUILD_SHA": "fixture-sha",
                    "CONTROL_PANEL_URL": backend,
                    "CONTROL_PANEL_UI_URL": backend,
                }
                proc = await asyncio.create_subprocess_exec(
                    str(BINARY),
                    env=env,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.DEVNULL,
                )
                try:
                    async with httpx.AsyncClient(trust_env=False, timeout=8) as rust:
                        for _ in range(150):
                            try:
                                health = await rust.get(f"http://127.0.0.1:{rust_port}/health")
                                if health.status_code == 200:
                                    break
                            except httpx.HTTPError:
                                pass
                            await asyncio.sleep(0.025)
                        else:
                            self.fail("Rust Gateway shadow did not become healthy")
                        self.assertEqual(
                            health.json(),
                            {
                                "status": "ok",
                                "node": "fixture-node",
                                "commit": "fixture-sha",
                            },
                        )
                        cases = [
                            ("GET", "/api/users?filter=a%2Fb", None),
                            ("POST", "/api/tool", '{"safe":true}'),
                            ("GET", "/admin/index.html", None),
                            ("GET", "/api/redirect", None),
                            ("GET", "/api/cookies", None),
                            ("GET", "/admin/api/realtime", None),
                        ]
                        for method, path, body in cases:
                            headers = {
                                "Host": "localhost:18080",
                                "Cookie": "session=test-fixture-cookie",
                                "X-Forwarded-Proto": "https",
                            }
                            expected = await python.request(
                                method, path, headers=headers, content=body
                            )
                            actual = await rust.request(
                                method,
                                f"http://127.0.0.1:{rust_port}{path}",
                                headers=headers,
                                content=body,
                            )
                            with self.subTest(method=method, path=path):
                                self.assertEqual(actual.status_code, expected.status_code)
                                if path.endswith("/redirect"):
                                    self.assertEqual(
                                        actual.headers.get("location"),
                                        expected.headers.get("location"),
                                    )
                                elif path.endswith("/cookies"):
                                    # Existing Python httpx header normalization merges two
                                    # Set-Cookie fields, which must not be reproduced in Rust.
                                    self.assertEqual(
                                        ", ".join(actual.headers.get_list("set-cookie")),
                                        expected.headers.get("set-cookie"),
                                    )
                                    self.assertEqual(len(actual.headers.get_list("set-cookie")), 2)
                                elif path.startswith("/admin/api/"):
                                    self.assertEqual(actual.status_code, 404)
                                else:
                                    self.assertEqual(actual.json(), expected.json())
                        for path, expected_code in [
                            ("/mcp", 404),
                            ("/observability/signoz/mcp", 401),
                            ("/unknown", 404),
                        ]:
                            result = await rust.post(
                                f"http://127.0.0.1:{rust_port}{path}",
                                headers={"Host": "briareus.example"},
                            )
                            self.assertEqual(result.status_code, expected_code)
                            if expected_code == 401:
                                self.assertIn("Bearer", result.headers.get("www-authenticate", ""))
                finally:
                    proc.terminate()
                    await asyncio.wait_for(proc.wait(), 6)
            await api.close()
            await ui.close()


if __name__ == "__main__":
    unittest.main()
