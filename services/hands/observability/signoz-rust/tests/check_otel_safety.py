"""Offline OpenTelemetry egress policy tests: no real collector or secrets.

Build Rust SigNoz pilot first. All endpoints and credentials are synthetic.
"""
from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import threading
import unittest
from contextlib import suppress
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
from fastmcp import Client

BINARY = Path(__file__).resolve().parents[1] / "target/debug/briareus-signoz-rust"
AUTH = "Bearer synthetic-otel-bearer-value"


class Sink:
    def __init__(self, *, redirect: bool, attacker_url: str = "") -> None:
        self.redirect = redirect
        self.attacker_url = attacker_url
        self.calls: list[tuple[str, bool, bool]] = []
        self.lock = threading.Lock()

        sink = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, _format: str, *_args: object) -> None:
                pass

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length", "0"))
                # Discard protobuf bytes; retain only safe metadata.
                _ = self.rfile.read(length)
                with sink.lock:
                    sink.calls.append(
                        (
                            self.path,
                            self.headers.get("Authorization") == AUTH,
                            bool(self.headers.get("Authorization")),
                        )
                    )
                self.send_response(307 if sink.redirect else 200)
                self.send_header("Content-Length", "0")
                if sink.redirect:
                    self.send_header("Location", sink.attacker_url + "/steal")
                self.end_headers()

        self.http = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.http.server_port}"

    def snapshot(self) -> list[tuple[str, bool, bool]]:
        with self.lock:
            return list(self.calls)

    def close(self) -> None:
        self.http.shutdown()
        self.http.server_close()
        self.thread.join(timeout=2)


def port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


class OTelTransportSafety(unittest.TestCase):
    def test_export_bearer_does_not_follow_redirect(self) -> None:
        asyncio.run(self.check_redirect())

    async def check_redirect(self) -> None:
        attacker = Sink(redirect=False)
        collector = Sink(redirect=True, attacker_url=attacker.url)
        chosen_port = port()
        env = {
            **os.environ,
            "CONTROL_PANEL_URL": "http://127.0.0.1:1",
            "BRIAREUS_SERVICE_TOKEN": "synthetic-panel-token",
            "OTEL_ENDPOINT": collector.url,
            "OTEL_BEARER_TOKEN": AUTH.removeprefix("Bearer "),
            "OTEL_METRIC_EXPORT_INTERVAL_MS": "1000",
            "OTEL_SERVICE_NAME": "briareus-signoz-rust-test",
            "DEPLOYMENT_ENVIRONMENT": "test",
            "PORT": str(chosen_port),
            "PRIVATE_MCP_ALLOWED_HOSTS": "127.0.0.1:*",
            "RUST_MCP_AUDIT_ENABLED": "false",
        }
        process = await asyncio.create_subprocess_exec(
            str(BINARY), env=env, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            for _ in range(130):
                if process.returncode is not None:
                    self.fail("Rust OTel test process exited unexpectedly")
                try:
                    async with httpx.AsyncClient(trust_env=False, timeout=0.4) as http:
                        r = await http.get(f"http://127.0.0.1:{chosen_port}/health/observability")
                        if r.status_code == 200:
                            self.assertTrue(r.json()["otel_enabled"])
                            break
                except (httpx.HTTPError, OSError):
                    pass
                await asyncio.sleep(0.05)
            else:
                self.fail("Rust OTel process readiness failed")

            async with Client(f"http://127.0.0.1:{chosen_port}/mcp", timeout=10) as cli:
                response = await cli.call_tool(
                    "signoz_sources", {}, raise_on_error=False
                )
                self.assertTrue(response.is_error)  # Panel deliberately absent.

            for _ in range(150):
                if {"/v1/metrics", "/v1/traces", "/v1/logs"} <= {
                    item[0] for item in collector.snapshot()
                }:
                    break
                await asyncio.sleep(0.06)
            called = collector.snapshot()
            self.assertTrue({"/v1/metrics", "/v1/traces", "/v1/logs"} <= {x[0] for x in called})
            self.assertTrue(all(authorized and has_header
                                for _, authorized, has_header in called))
            # Even with 307 and a trusted POST source, never redirect the bearer.
            self.assertEqual(attacker.snapshot(), [])
        finally:
            process.terminate()
            with suppress(TimeoutError):
                await asyncio.wait_for(process.wait(), timeout=6)
            if process.returncode is None:
                process.kill()
                await asyncio.wait_for(process.wait(), timeout=3)
            collector.close()
            attacker.close()


if __name__ == "__main__":
    unittest.main()
