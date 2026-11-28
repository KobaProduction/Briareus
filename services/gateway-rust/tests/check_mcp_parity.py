"""Exercise authenticated Rust MCP frontend sessions against real local FastMCP Hands."""

from __future__ import annotations

import asyncio
import json
import sys
import time
import unittest
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
import jwt
import uvicorn
from fastmcp import FastMCP
from fixture_server import FixtureServer
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp, Receive, Scope, Send

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "services/gateway-rust/tests"))
from check_oidc_parity import free_port, issuer_fixture, rust_gateway  # noqa: E402


def rpc(response: httpx.Response) -> dict[str, Any]:
    if response.headers.get("content-type", "").startswith("application/json"):
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                continue
    raise AssertionError(f"Unexpected MCP response {response.status_code}: {response.text[:240]}")


@dataclass
class InitializeFault:
    """Synthetic transport interruption, not an upstream business operation."""

    remaining: int = 1
    attempts: int = 0

    def wrap(self, app: ASGIApp) -> ASGIApp:
        async def handler(scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] != "http" or scope["method"] != "POST":
                await app(scope, receive, send)
                return
            request = Request(scope, receive)
            raw: bytes | None = await request.body()
            message = json.loads(raw)
            if isinstance(message, dict) and message.get("method") == "initialize":
                self.attempts += 1
                if self.remaining:
                    self.remaining -= 1
                    await Response(b"", media_type="text/event-stream")(scope, receive, send)
                    return

            async def replay() -> dict[str, Any]:
                nonlocal raw
                if raw is not None:
                    body, raw = raw, None
                    return {"type": "http.request", "body": body, "more_body": False}
                return await receive()

            await app(scope, replay, send)

        return handler


@asynccontextmanager
async def provider_fixture(
    service_name: str, *, initialize_fault: InitializeFault | None = None
) -> AsyncIterator[tuple[str, FastMCP[Any]]]:
    handler: FastMCP[Any] = FastMCP(service_name)

    @handler.tool
    def identify_fixture() -> dict[str, str]:
        """Return a fixed marker that identifies the selected MCP Hand."""
        return {"provider": service_name}

    @handler.tool
    def add_numbers(left: int, right: int) -> int:
        """Add two numbers with an explicitly typed input schema."""
        return left + right

    @handler.resource("fixture://marker")
    def fixture_marker() -> str:
        """Expose a provider-specific resource via the MCP resource interface."""
        return "Resource from " + service_name

    @handler.prompt
    def fixture_prompt() -> str:
        """Expose a provider-specific prompt via the MCP prompt interface."""
        return "Prompt from " + service_name

    app = handler.http_app(path="/mcp")
    transport = initialize_fault.wrap(app) if initialize_fault else app
    port = free_port()
    server = FixtureServer(
        uvicorn.Config(
            transport,
            host="127.0.0.1",
            port=port,
            log_level="error",
            lifespan="on",
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
            raise RuntimeError("FastMCP fixture startup failed")
        yield f"http://127.0.0.1:{port}", handler
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, 6)


class McpSessionContract(unittest.IsolatedAsyncioTestCase):
    async def test_isolated_frontend_sessions_backend_reuse_and_tool_results(self) -> None:
        async with (
            issuer_fixture() as (issuer, pem),
            provider_fixture("GitHub Synthetic") as (github, _github_handler),
            provider_fixture("SigNoz Synthetic") as (signoz, _signoz_handler),
            rust_gateway(
                issuer, "list", '["roles"]', "", targets={"github": github, "signoz": signoz}
            ) as (client, endpoint),
        ):
            now = int(time.time())
            token = jwt.encode(
                {
                    "iss": issuer,
                    "aud": "fixture-project",
                    "sub": "fixture-user",
                    "client_id": "fixture-client",
                    "exp": now + 240,
                    "iat": now - 10,
                    "roles": ["tambov"],
                },
                pem,
                algorithm="RS256",
                headers={"kid": "fixture-key-1"},
            )
            routes = [
                (
                    endpoint.replace("/observability/signoz/mcp", "/svc/github/mcp"),
                    "GitHub Synthetic",
                ),
                (endpoint, "SigNoz Synthetic"),
            ]
            for path, name in routes:
                auth = {
                    "Authorization": "Bearer " + token,
                    "Accept": "application/json, text/event-stream",
                    "Content-Type": "application/json",
                }
                init = await client.post(
                    path,
                    headers=auth,
                    json={
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "initialize",
                        "params": {
                            "protocolVersion": "2025-03-26",
                            "capabilities": {},
                            "clientInfo": {"name": "rust-gateway-parity", "version": "1"},
                        },
                    },
                )
                with self.subTest(route=path, method="initialize"):
                    self.assertEqual(init.status_code, 200, init.text[:400])
                    self.assertIn("result", rpc(init))
                frontend = init.headers.get("mcp-session-id")
                if frontend:
                    auth["Mcp-Session-Id"] = frontend
                await client.post(
                    path,
                    headers=auth,
                    json={
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    },
                )
                listed = await client.post(
                    path,
                    headers=auth,
                    json={
                        "jsonrpc": "2.0",
                        "id": 2,
                        "method": "tools/list",
                        "params": {},
                    },
                )
                with self.subTest(route=path, method="tools/list"):
                    self.assertEqual(listed.status_code, 200, listed.text[:400])
                    names = [x["name"] for x in rpc(listed)["result"]["tools"]]
                    self.assertEqual(sorted(names), ["add_numbers", "identify_fixture"])
                called = await client.post(
                    path,
                    headers=auth,
                    json={
                        "jsonrpc": "2.0",
                        "id": 3,
                        "method": "tools/call",
                        "params": {"name": "identify_fixture", "arguments": {}},
                    },
                )
                with self.subTest(route=path, method="tools/call"):
                    self.assertEqual(called.status_code, 200, called.text[:400])
                    result = rpc(called)["result"]
                    self.assertFalse(result.get("isError", False), result)
                    self.assertEqual(result["structuredContent"]["provider"], name)
                for number, method, params, key, expected_name in (
                    (20, "resources/list", {}, "resources", "fixture://marker"),
                    (21, "prompts/list", {}, "prompts", "fixture_prompt"),
                ):
                    response = await client.post(
                        path,
                        headers=auth,
                        json={
                            "jsonrpc": "2.0",
                            "id": number,
                            "method": method,
                            "params": params,
                        },
                    )
                    with self.subTest(route=path, method=method):
                        self.assertEqual(response.status_code, 200, response.text[:500])
                        records = rpc(response)["result"][key]
                        self.assertIn(expected_name, [x.get("uri", x.get("name")) for x in records])
                for number, method, params in (
                    (22, "resources/read", {"uri": "fixture://marker"}),
                    (23, "prompts/get", {"name": "fixture_prompt", "arguments": {}}),
                ):
                    response = await client.post(
                        path,
                        headers=auth,
                        json={
                            "jsonrpc": "2.0",
                            "id": number,
                            "method": method,
                            "params": params,
                        },
                    )
                    with self.subTest(route=path, method=method):
                        self.assertEqual(response.status_code, 200, response.text[:500])
                        self.assertIn(name, json.dumps(rpc(response)["result"]))
                concurrent = await asyncio.gather(
                    *(
                        client.post(
                            path,
                            headers=auth,
                            json={
                                "jsonrpc": "2.0",
                                "id": 100 + n,
                                "method": "tools/call",
                                "params": {
                                    "name": "add_numbers",
                                    "arguments": {"left": n, "right": 3},
                                },
                            },
                        )
                        for n in range(12)
                    )
                )
                for n, response in enumerate(concurrent):
                    with self.subTest(route=path, method="concurrent", n=n):
                        self.assertEqual(response.status_code, 200, response.text[:500])
                        result = rpc(response)["result"]
                        self.assertFalse(result.get("isError", False), result)
                        self.assertEqual(result["structuredContent"]["result"], n + 3)
                invalid_tool = await client.post(
                    path,
                    headers=auth,
                    json={
                        "jsonrpc": "2.0",
                        "id": 240,
                        "method": "tools/call",
                        "params": {"name": "does_not_exist", "arguments": {}},
                    },
                )
                self.assertEqual(invalid_tool.status_code, 200)
                invalid_result = rpc(invalid_tool)
                self.assertTrue(
                    invalid_result.get("error") is not None
                    or invalid_result.get("result", {}).get("isError", False)
                )
                denied = await client.post(
                    path,
                    headers={
                        **auth,
                        "Authorization": "Bearer invalid",
                    },
                    json={"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
                )
                self.assertEqual(denied.status_code, 401)
                # The frontend session ID alone is not an authorization grant.
                if frontend:
                    denial = await client.get(
                        path,
                        headers={
                            "Mcp-Session-Id": frontend,
                            "Accept": "text/event-stream",
                        },
                    )
                    self.assertEqual(denial.status_code, 401)
            # No unknown root MCP connection is added to the Gateway.
            self.assertEqual(
                (
                    await client.post(
                        endpoint.replace("/observability/signoz/mcp", "/mcp"),
                        headers={"Authorization": "Bearer " + token},
                    )
                ).status_code,
                404,
            )


if __name__ == "__main__":
    unittest.main()
