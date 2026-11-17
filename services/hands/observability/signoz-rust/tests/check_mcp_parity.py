"""Offline MCP parity harness: no live credentials, deployments or Docker.

Build with cargo build --locked, then run this file using the V1 Python interpreter.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

HERE = Path(__file__).resolve()
ROOT = HERE.parents[5]
assert (ROOT / "deploy/services.json").is_file(), "Wrong source root"
sys.path.insert(0, str(ROOT))
from tests.run_briareus_contracts import source_roots  # noqa: E402

sys.path[0:0] = [str(p) for p in source_roots()]
import httpx  # noqa: E402
from briareus_account_contracts import ResolvedAccount  # noqa: E402
from briareus_signoz.client import SigNozClient  # noqa: E402
from fastmcp import Client  # noqa: E402

BINARY = HERE.parents[1] / "target/debug/briareus-signoz-rust"
PANEL_TOKEN = "synthetic-panel-token"
SIGNOZ_KEY = "synthetic-signoz-api-key"


class Recorder:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.requests: list[tuple[str, str, object]] = []

    def add(self, method: str, path: str, value: object) -> None:
        with self.lock:
            self.requests.append((method, path, value))


def make_server(role: str, recorder: Recorder, signoz_url: str = "") -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

        def respond(self, payload: object, status: int = 200) -> None:
            body = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def authorized(self) -> bool:
            if role == "panel":
                return self.headers.get("Authorization") == f"Bearer {PANEL_TOKEN}"
            return self.headers.get("SIGNOZ-API-KEY") == SIGNOZ_KEY

        def do_GET(self) -> None:
            if not self.authorized():
                self.respond({}, 401)
                return
            recorder.add("GET", self.path, None)
            path = urlsplit(self.path).path
            account = {
                "id": "test-id",
                "alias": "fixture",
                "provider": "signoz",
                "auth_type": "signoz_api_key",
                "base_url": signoz_url,
                "credential": SIGNOZ_KEY,
                "verify_tls": True,
                "enabled": True,
                "created_at": "created",
                "updated_at": "updated",
            }
            if role == "panel" and path == "/internal/accounts":
                self.respond({"accounts": [account], "count": 1})
            elif role == "panel" and path == "/internal/accounts/test-id/resolve":
                self.respond(account)
            elif role == "signoz" and path.startswith("/api/v1/fields/"):
                self.respond({"data": {"path": self.path}})
            else:
                self.respond({}, 404)

        def do_POST(self) -> None:
            if not self.authorized():
                self.respond({}, 401)
                return
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length))
            recorder.add("POST", self.path, payload)
            if role == "panel" and urlsplit(self.path).path == "/internal/events/batch":
                self.send_response(204)
                self.send_header("Content-Length", "0")
                self.end_headers()
            elif role == "signoz" and urlsplit(self.path).path in (
                "/api/v5/query_range", "/api/v1/services"
            ):
                self.respond({"data": {"request": payload}})
            else:
                self.respond({}, 404)

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def make_otel_collector(recorder: Recorder) -> ThreadingHTTPServer:
    """Local fake OTLP collector; only safe path/count/secret-absence is retained."""
    class Collector(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: object) -> None:
            pass

        def do_POST(self) -> None:
            size = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(size)
            recorder.add(
                "OTLP",
                self.path,
                {
                    "size": size,
                    "authorized": self.headers.get("Authorization")
                    == "Bearer synthetic-otel-token",
                    "contains_provider_key": SIGNOZ_KEY.encode() in body,
                    "contains_panel_token": PANEL_TOKEN.encode() in body,
                    "contains_filter": b"severity_text = " in body,
                },
            )
            self.send_response(200)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return ThreadingHTTPServer(("127.0.0.1", 0), Collector)


def spare_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


class RustSigNozParity(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not BINARY.exists():
            raise RuntimeError("Build the Rust pilot binary before MCP parity tests")
        cls.recorder = Recorder()
        cls.signoz = make_server("signoz", cls.recorder)
        cls.otel = make_otel_collector(cls.recorder)
        cls.signoz_url = f"http://127.0.0.1:{cls.signoz.server_port}"
        cls.panel = make_server("panel", cls.recorder, cls.signoz_url)
        for server in (cls.signoz, cls.panel, cls.otel):
            threading.Thread(target=server.serve_forever, daemon=True).start()
        cls.port = spare_port()
        env = {
            **os.environ,
            "BRIAREUS_SERVICE_TOKEN": PANEL_TOKEN,
            "CONTROL_PANEL_URL": f"http://127.0.0.1:{cls.panel.server_port}",
            "PORT": str(cls.port),
            "PRIVATE_MCP_ALLOWED_HOSTS": "127.0.0.1:*",
            "RUST_MCP_AUDIT_ENABLED": "true",
            "RUST_MCP_AUDIT_QUEUE_ENTRIES": "8",
            "OTEL_ENDPOINT": f"http://127.0.0.1:{cls.otel.server_port}",
            "OTEL_BEARER_TOKEN": "synthetic-otel-token",
            "OTEL_METRIC_EXPORT_INTERVAL_MS": "1000",
            "OTEL_SERVICE_NAME": "briareus-signoz-rust-test",
            "DEPLOYMENT_ENVIRONMENT": "test",
        }
        cls.process = subprocess.Popen(
            [str(BINARY)], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, env=env
        )
        for _ in range(120):
            if cls.process.poll() is not None:
                raise RuntimeError("Rust MCP pilot stopped before readiness")
            try:
                if httpx.get(f"http://127.0.0.1:{cls.port}/health", timeout=0.3).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise RuntimeError("Rust MCP pilot readiness timed out")

    @classmethod
    def tearDownClass(cls) -> None:
        if hasattr(cls, "process"):
            cls.process.terminate()
            try:
                cls.process.wait(timeout=4)
            except subprocess.TimeoutExpired:
                cls.process.kill()
                cls.process.wait(timeout=4)
        for server in (
            getattr(cls, "panel", None), getattr(cls, "signoz", None),
            getattr(cls, "otel", None),
        ):
            if server:
                server.shutdown()
                server.server_close()

    def test_mcp_and_wire_parity(self) -> None:
        asyncio.run(self.check_mcp())

    async def check_otel_export(self) -> None:
        # The official OTel exporter must emit all three signals with only
        # static tool outcomes, not payloads or credentials, to our fake collector.
        signals = {}
        for _ in range(100):
            with self.recorder.lock:
                signals = {
                    path: payload
                    for method, path, payload in self.recorder.requests
                    if method == "OTLP"
                }
            if {"/v1/traces", "/v1/logs", "/v1/metrics"} <= signals.keys():
                break
            await asyncio.sleep(0.06)
        self.assertEqual(set(signals), {"/v1/traces", "/v1/logs", "/v1/metrics"})
        for path, safe in signals.items():
            self.assertGreater(safe["size"], 0, path)
            self.assertTrue(safe["authorized"], path)
            self.assertFalse(safe["contains_provider_key"], path)
            self.assertFalse(safe["contains_panel_token"], path)
            self.assertFalse(safe["contains_filter"], path)


    async def check_mcp(self) -> None:
        async with Client(f"http://127.0.0.1:{self.port}/mcp", timeout=8) as mcp:
            tools = await mcp.list_tools()
            names = {t.name for t in tools}
            expected = {
                "signoz_sources", "signoz_connection", "signoz_search_logs",
                "signoz_search_traces", "signoz_query_telemetry",
                "signoz_list_services", "signoz_field_keys", "signoz_field_values",
            }
            self.assertEqual(names, expected)
            tools_by_name = {t.name: t for t in tools}
            for name in expected - {"signoz_sources"}:
                self.assertIn("account_id", tools_by_name[name].input_schema["required"])

            unwrapped_schema = {"type": "object", "additionalProperties": {}}
            wrapped_schema = {
                "type": "object",
                "properties": {"result": {}},
                "required": ["result"],
                "x-fastmcp-wrap-result": True,
            }
            for name in {"signoz_sources", "signoz_connection"}:
                self.assertEqual(tools_by_name[name].output_schema, unwrapped_schema)
            for name in expected - {"signoz_sources", "signoz_connection"}:
                self.assertEqual(tools_by_name[name].output_schema, wrapped_schema)

            sources = await mcp.call_tool("signoz_sources", {})
            self.assertFalse(sources.is_error)
            self.assertEqual(sources.structured_content["count"], 1)
            self.assertNotIn(SIGNOZ_KEY, str(sources.structured_content))

            a = {"account_id": "test-id"}
            connection = await mcp.call_tool("signoz_connection", a)
            self.assertTrue(connection.structured_content["credential_configured"])
            self.assertNotIn(SIGNOZ_KEY, str(connection.structured_content))

            python = SigNozClient(ResolvedAccount(
                id="test-id", alias="fixture", provider="signoz",
                auth_type="signoz_api_key", base_url=self.signoz_url,
                credential=SIGNOZ_KEY, created_at="created", updated_at="updated",
            ))
            with patch.object(python, "query_range", side_effect=lambda data: data):
                expected_logs = python.search_logs(
                    start_ms=100, end_ms=200, filter_expression="severity_text = 'ERROR'",
                    limit=17, offset=2
                )
                expected_traces = python.search_traces(
                    start_ms=100, end_ms=200, filter_expression="service.name = 'api'",
                    limit=17, offset=2
                )
            q = {**a, "start_ms":100, "end_ms":200, "limit":17, "offset":2,
                 "filter_expression":"severity_text = 'ERROR'"}
            logs = await mcp.call_tool("signoz_search_logs", q)
            self.assertEqual(logs.structured_content["result"]["data"]["request"], expected_logs)
            q["filter_expression"] = "service.name = 'api'"
            traces = await mcp.call_tool("signoz_search_traces", q)
            self.assertEqual(
                traces.structured_content["result"]["data"]["request"],
                expected_traces,
            )
            query = {"requestType":"raw", "variables":{}, "compositeQuery":{"queries":[]}}
            telemetry = await mcp.call_tool("signoz_query_telemetry", {**a,"query":query})
            self.assertEqual(telemetry.structured_content["result"]["data"]["request"], query)

            services = await mcp.call_tool("signoz_list_services", {
                **a, "start":"2026-11-11T00:00:00Z", "end":"1794441600000"
            })
            self.assertEqual(services.structured_content["result"]["data"]["request"], {
                "start":"1794355200000000000", "end":"1794441600000000000"
            })
            keys = await mcp.call_tool("signoz_field_keys", {
                **a, "signal":"logs", "search_text":"http"
            })
            self.assertIn("searchText=http", keys.structured_content["result"]["data"]["path"])
            values = await mcp.call_tool("signoz_field_values", {
                **a, "signal":"logs", "name":"service.name"
            })
            self.assertIn("name=service.name", values.structured_content["result"]["data"]["path"])
            for response in [logs, traces, telemetry, services, keys, values]:
                self.assertEqual(
                    json.loads(response.content[0].text),
                    response.structured_content["result"],
                    "Python-compatible raw JSON text and wrapped structured result"
                )
            invalid = await mcp.call_tool(
                "signoz_search_logs", {**a,"start_ms":200,"end_ms":100},
                raise_on_error=False
            )
            self.assertTrue(invalid.is_error)
            self.assertNotIn(SIGNOZ_KEY, str(invalid))
            missing = await mcp.call_tool(
                "signoz_connection", {"account_id":"missing"}, raise_on_error=False
            )
            self.assertTrue(missing.is_error)
            self.assertNotIn(PANEL_TOKEN, str(missing))

        # Check the actual private audit POST, not merely a mock reporter.
        # All tool outcomes (including failures) are required; no queries,
        # filters, credentials, or provider response body may enter history.
        events = []
        for _ in range(40):
            await asyncio.sleep(0.05)
            with self.recorder.lock:
                events = [
                    entry for method, path, payload in self.recorder.requests
                    if method == "POST" and path == "/internal/events/batch"
                    for entry in payload["events"]
                ]
            if len(events) >= 10:
                break
        self.assertGreaterEqual(len(events), 10, "Audit worker must flush all 10 calls")
        async with httpx.AsyncClient(timeout=4.0, trust_env=False) as http:
            counters = (
                await http.get(f"http://127.0.0.1:{self.port}/health/observability")
            ).json()
        self.assertTrue(counters["enabled"])
        self.assertTrue(counters["otel_enabled"])
        self.assertGreaterEqual(counters["accepted_events"], 10)
        self.assertGreaterEqual(counters["accepted_batches"], 1)
        self.assertEqual(counters["queued_events"], 0)
        self.assertEqual(counters["failed_batches"], 0)
        self.assertEqual(counters["dropped_events"], 0)
        for prohibited in (PANEL_TOKEN, SIGNOZ_KEY, "test-id", "logs", "provider"):
            self.assertNotIn(prohibited, json.dumps(counters))
        by_tool = {event["tool"]: event for event in events}
        self.assertEqual(by_tool["signoz_search_logs"]["status"], "error")
        self.assertEqual(by_tool["signoz_connection"]["status"], "error")
        self.assertEqual(by_tool["signoz_sources"]["status"], "success")
        self.assertEqual(by_tool["signoz_field_keys"]["status"], "success")
        self.assertEqual(by_tool["signoz_field_keys"]["account_id"], "test-id")
        for event in events:
            self.assertEqual(event["module"], "signoz")
            self.assertIn(event["status"], {"success", "error"})
            self.assertGreaterEqual(event["duration_ms"], 0)
            self.assertEqual(json.loads(event["arguments_json"])["detail"],
                             "Rust Hand arguments omitted from audit")
            if event["status"] == "success":
                self.assertEqual(json.loads(event["result_json"])["detail"],
                                 "Rust Hand result omitted from audit")
        encoded = json.dumps(events)
        for private in (PANEL_TOKEN, SIGNOZ_KEY,
                        "severity_text = 'ERROR'", "service.name = 'api'",
                        '"requestType":"raw"'):
            self.assertNotIn(private, encoded)

        await self.check_otel_export()

        self.assertTrue(all(t.annotations and t.annotations.read_only_hint for t in tools),
                        "Rust MCP tools must advertise read-only metadata like the Python Hand")

        status = await asyncio.to_thread(Path(f"/proc/{self.process.pid}/status").read_text)
        rss = next((x.split()[1] for x in status.splitlines()
                    if x.startswith("VmRSS:")), "unknown")
        print(f"Rust MCP pilot: 8/8 tools, Python query parity; VmRSS_kib={rss}")


if __name__ == "__main__":
    unittest.main()
