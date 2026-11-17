"""Isolated adversarial network tests for the parallel Rust SigNoz Hand.

No live credentials, Docker, redis, production providers or public Gateway.
Build the Rust binary first; override BRIAREUS_RUST_SIGNOZ_BINARY when needed.
"""

from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import threading
import time
import unittest
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from fastmcp import Client

BINARY = Path(
    os.environ.get(
        "BRIAREUS_RUST_SIGNOZ_BINARY",
        str(Path(__file__).resolve().parents[1] / "target/debug/briareus-signoz-rust"),
    )
)
PANEL_TOKEN = "synthetic-control-panel-token"
API_KEY = "synthetic-signoz-api-key"
PROVIDER_SECRET = "synthetic-upstream-sensitive-body"
LIMIT = 8 * 1024 * 1024


class Record:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.paths: list[str] = []

    def add(self, path: str) -> None:
        with self.lock:
            self.paths.append(path)

    def snapshot(self) -> list[str]:
        with self.lock:
            return list(self.paths)


def spare_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


class FixtureHandler(BaseHTTPRequestHandler):
    server: FixtureServer

    def log_message(self, _format: str, *_args: object) -> None:
        pass

    def send(
        self,
        data: bytes,
        status: int = 200,
        *,
        content_type: str = "application/json",
        location: str | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        if location:
            self.send_header("Location", location)
        self.end_headers()
        # A bounded consumer intentionally stops reading oversized JSON.
        with suppress(BrokenPipeError, ConnectionResetError):
            self.wfile.write(data)

    def send_json(self, data: object, status: int = 200) -> None:
        self.send(json.dumps(data).encode(), status)

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if self.server.role == "panel":
            self.server.fixture.panel_calls.add(self.path)
            if self.headers.get("SIGNOZ-API-KEY"):
                self.server.fixture.cross_boundary_auth_leak = True
            if self.headers.get("Authorization") != f"Bearer {PANEL_TOKEN}":
                self.send_json({}, 401)
            elif path == "/internal/accounts/test-id/resolve":
                self.send_json(self.server.fixture.account())
            elif path == "/internal/accounts":
                account = self.server.fixture.account()
                account.pop("credential")
                self.send_json({"accounts": [account], "count": 1})
            else:
                self.send_json({}, 404)
        elif self.server.role == "attacker":
            self.server.fixture.attacker_calls.add(self.path)
            self.send_json({})
        else:
            self.server.fixture.provider_calls.add(self.path)
            if self.headers.get("SIGNOZ-API-KEY") != self.server.fixture.provider_key:
                self.send_json({"detail": PROVIDER_SECRET}, 401)
            else:
                self.send_json({"ok": True, "path": self.path})

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        self.rfile.read(length)
        if self.server.role == "attacker":
            self.server.fixture.attacker_calls.add(self.path)
            self.send_json({"leak": True})
            return
        if self.server.role != "signoz":
            self.send_json({}, 405)
            return
        self.server.fixture.provider_calls.add(self.path)
        if self.headers.get("Authorization"):
            self.server.fixture.cross_boundary_auth_leak = True
        if self.headers.get("SIGNOZ-API-KEY") != self.server.fixture.provider_key:
            self.send_json({"detail": PROVIDER_SECRET}, 401)
        elif path != "/api/v5/query_range":
            self.send_json({}, 404)
        elif self.server.fixture.mode == "redirect":
            self.send(b"", 307, location=self.server.fixture.attacker_url + "/capture")
        elif self.server.fixture.mode == "forbidden":
            self.send_json({"secret": PROVIDER_SECRET}, 403)
        elif self.server.fixture.mode == "malformed":
            self.send(b"not-json", 200)
        elif self.server.fixture.mode == "oversized":
            self.send(b'{"message":"' + b"a" * (LIMIT + 1) + b'"}')
        else:
            self.send_json({"data": {"ok": True}})


class FixtureServer(ThreadingHTTPServer):
    def __init__(self, fixture: Fixture, role: str) -> None:
        self.fixture = fixture
        self.role = role
        super().__init__(("127.0.0.1", 0), FixtureHandler)


class Fixture:
    def __init__(self) -> None:
        self.mode = "normal"
        self.account_provider = "signoz"
        self.provider_key = API_KEY
        self.account_key = API_KEY
        self.panel_calls = Record()
        self.provider_calls = Record()
        self.attacker_calls = Record()
        self.cross_boundary_auth_leak = False

        self.panel = FixtureServer(self, "panel")
        self.signoz = FixtureServer(self, "signoz")
        self.attacker = FixtureServer(self, "attacker")
        self.attacker_url = f"http://127.0.0.1:{self.attacker.server_port}"
        self.threads = [
            threading.Thread(target=s.serve_forever, daemon=True)
            for s in (self.panel, self.signoz, self.attacker)
        ]
        for thread in self.threads:
            thread.start()

    def account(self) -> dict[str, object]:
        return {
            "id": "test-id",
            "alias": "fixture",
            "provider": self.account_provider,
            "auth_type": "api_key",
            "base_url": f"http://127.0.0.1:{self.signoz.server_port}",
            "credential": self.account_key,
            "created_at": "created",
            "updated_at": "revision-1",
            "enabled": True,
            "verify_tls": True,
        }

    def close(self) -> None:
        for server in (self.panel, self.signoz, self.attacker):
            server.shutdown()
            server.server_close()


class RustSigNozNetworkSafety(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BINARY.is_file():
            raise RuntimeError(f"Rust SigNoz pilot binary is missing: {BINARY}")
        cls.fixture = Fixture()
        cls.port = spare_port()
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.environment = {
            **os.environ,
            "BRIAREUS_SERVICE_TOKEN": PANEL_TOKEN,
            "CONTROL_PANEL_URL": f"http://127.0.0.1:{cls.fixture.panel.server_port}",
            "PORT": str(cls.port),
            "BIND_HOST": "127.0.0.1",
            "PRIVATE_MCP_ALLOWED_HOSTS": "localhost:*,127.0.0.1:*",
            "PRIVATE_MCP_ALLOWED_ORIGINS": "http://localhost:*,http://127.0.0.1:*",
        }
        cls.process = subprocess.Popen(
            [str(BINARY)],
            env=cls.environment,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        for _ in range(80):
            if cls.process.poll() is not None:
                raise RuntimeError("Rust SigNoz pilot exited before readiness")
            try:
                if httpx.get(cls.url + "/health", timeout=0.5).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("Rust SigNoz pilot health timeout")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "process"):
            cls.process.terminate()
            try:
                cls.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=4)
        if hasattr(cls, "fixture"):
            cls.fixture.close()

    def setUp(self) -> None:
        self.fixture.mode = "normal"
        self.fixture.account_provider = "signoz"
        self.fixture.account_key = API_KEY
        self.fixture.provider_key = API_KEY

    async def invoke(self) -> object:
        async with Client(self.url + "/mcp", timeout=12) as mcp:
            return await mcp.call_tool(
                "signoz_query_telemetry",
                {"account_id": "test-id", "query": {"requestType": "raw"}},
                raise_on_error=False,
            )

    def test_01_bad_host_is_rejected_before_mcp_dispatch(self) -> None:
        result = httpx.post(
            self.url + "/mcp",
            timeout=4,
            headers={
                "Host": "attacker.example:9000",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        self.assertIn(result.status_code, (400, 403))

    def test_02_untrusted_origin_is_rejected(self) -> None:
        result = httpx.post(
            self.url + "/mcp",
            timeout=4,
            headers={
                "Origin": "https://attacker.example",
                "Accept": "application/json, text/event-stream",
            },
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            },
        )
        self.assertIn(result.status_code, (400, 403))

    def test_03_follows_no_redirect_with_provider_key(self) -> None:
        self.fixture.mode = "redirect"
        before = len(self.fixture.attacker_calls.snapshot())
        result = asyncio.run(self.invoke())
        self.assertTrue(result.is_error)
        self.assertEqual(len(self.fixture.attacker_calls.snapshot()), before)
        self.assertNotIn(API_KEY, str(result))

    def test_04_provider_forbidden_body_is_not_returned(self) -> None:
        self.fixture.mode = "forbidden"
        result = asyncio.run(self.invoke())
        self.assertTrue(result.is_error)
        self.assertIn("403", str(result))
        self.assertNotIn(PROVIDER_SECRET, str(result))
        self.assertNotIn(API_KEY, str(result))

    def test_05_provider_401_does_not_reveal_credentials(self) -> None:
        self.fixture.provider_key = "different-fixture-key"
        result = asyncio.run(self.invoke())
        self.assertTrue(result.is_error)
        self.assertIn("401", str(result))
        self.assertNotIn(PROVIDER_SECRET, str(result))
        self.assertNotIn(API_KEY, str(result))

    def test_06_malformed_upstream_json_is_tool_error(self) -> None:
        self.fixture.mode = "malformed"
        result = asyncio.run(self.invoke())
        self.assertTrue(result.is_error)
        self.assertNotIn("not-json", str(result))

    def test_07_oversized_upstream_json_is_tool_error(self) -> None:
        self.fixture.mode = "oversized"
        result = asyncio.run(self.invoke())
        self.assertTrue(result.is_error)
        self.assertLess(len(str(result)), 1000)

    def test_08_rejects_cross_provider_account(self) -> None:
        self.fixture.account_provider = "github"
        before = len(self.fixture.provider_calls.snapshot())
        result = asyncio.run(self.invoke())
        self.assertTrue(result.is_error)
        self.assertEqual(len(self.fixture.provider_calls.snapshot()), before)
        self.assertNotIn(API_KEY, str(result))

    def test_09_account_credential_rotation_is_used(self) -> None:
        self.fixture.account_key = "rotated-synthetic-key"
        self.fixture.provider_key = "rotated-synthetic-key"
        result = asyncio.run(self.invoke())
        self.assertFalse(result.is_error)
        self.assertTrue(result.structured_content["data"]["ok"])

    def test_10_missing_control_panel_token_prevents_startup(self) -> None:
        env = {**self.environment, "BRIAREUS_SERVICE_TOKEN": ""}
        process = subprocess.Popen(
            [str(BINARY)],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            self.assertNotEqual(process.wait(timeout=5), 0)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=4)

    def test_11_no_cross_service_authorization_headers(self) -> None:
        result = asyncio.run(self.invoke())
        self.assertFalse(result.is_error)
        self.assertFalse(
            self.fixture.cross_boundary_auth_leak,
            "provider token crossed the Control Panel boundary (or vice versa)",
        )


if __name__ == "__main__":
    unittest.main()
