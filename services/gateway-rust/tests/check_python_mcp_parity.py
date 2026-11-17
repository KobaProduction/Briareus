"""Compare Rust MCP facade with the same Python Gateway implementation and Hands."""

from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
from starlette.applications import Starlette
from starlette.routing import Mount

ROOT = Path(__file__).resolve().parents[3]
for module in ROOT.glob("shared/**/src/*/__init__.py"):
    sys.path.insert(0, str(module.parent.parent))
sys.path.insert(0, str(ROOT / "services/gateway/src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from briareus_service_catalog import ServiceDefinition  # noqa: E402
from briareus_service_discovery import (  # noqa: E402
    DiscoveredService,
    DiscoverySnapshot,
    ServiceDiscovery,
)
from check_mcp_parity import provider_fixture, rpc  # noqa: E402
from check_oidc_parity import issuer_fixture, rust_gateway  # noqa: E402
from gateway.gateway_settings import GatewayAuthSettings  # noqa: E402
from gateway.service_routes import ServiceMcpRoutes  # noqa: E402
from gateway.settings import GatewaySettings  # noqa: E402


async def timeout() -> float:
    return 10.0


async def initialized_client(client: httpx.AsyncClient, path: str, token: str) -> dict[str, str]:
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json, text/event-stream",
        "Content-Type": "application/json",
    }
    initialized = await client.post(
        path,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "rust-python-parity", "version": "1"},
            },
        },
    )
    if initialized.status_code != 200:
        raise AssertionError(f"Initialize failed status={initialized.status_code}")
    if "result" not in rpc(initialized):
        raise AssertionError("Initialize has no MCP result")
    if session := initialized.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = session
    await client.post(
        path,
        headers=headers,
        json={
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
        },
    )
    return headers


class PythonRustMcpParity(unittest.IsolatedAsyncioTestCase):
    async def test_tool_schemas_resources_and_results(self) -> None:
        async with (
            issuer_fixture() as (issuer, pem),
            provider_fixture("GitHub Synthetic") as (github, github_server),
            provider_fixture("SigNoz Synthetic") as (signoz, signoz_server),
            rust_gateway(
                issuer, "list", '["roles"]', "", targets={"github": github, "signoz": signoz}
            ) as (rust, rust_root),
        ):
            records = (
                ServiceDefinition(id="github", name="GitHub", group="svc"),
                ServiceDefinition(id="signoz", name="SigNoz", group="observability"),
            )
            snapshot = DiscoverySnapshot(
                services=tuple(
                    DiscoveredService(
                        id=entry.id,
                        name=entry.name,
                        group=entry.group,
                        connected=True,
                        mcp_path=entry.mcp_path,
                    )
                    for entry in records
                ),
                checked_at=__import__("datetime").datetime.now(__import__("datetime").UTC),
            )
            discovery = MagicMock(spec=ServiceDiscovery)
            discovery.snapshot = AsyncMock(return_value=snapshot)
            routes = ServiceMcpRoutes(
                discovery,
                GatewaySettings(),
                GatewayAuthSettings(
                    issuer_url=issuer,
                    audience="fixture-project",
                    required_role="tambov",
                    roles_claim_path=("roles",),
                    public_base_url="https://briareus.example",
                ),
                timeout,
                targets={"github": github_server, "signoz": signoz_server},
            )
            now = int(time.time())
            bearer = jwt.encode(
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
            async with (
                routes.lifespan(),
                httpx.AsyncClient(
                    transport=httpx.ASGITransport(Starlette(routes=[Mount("/", routes)])),
                    base_url="https://briareus.example",
                    trust_env=False,
                    timeout=20,
                ) as python,
            ):
                for entry in records:
                    headers_python = await initialized_client(python, entry.mcp_path, bearer)
                    rust_path = rust_root.replace("/observability/signoz/mcp", entry.mcp_path)
                    headers_rust = await initialized_client(rust, rust_path, bearer)
                    requests = (
                        ("tools/list", {}),
                        ("tools/call", {"name": "identify_fixture", "arguments": {}}),
                        (
                            "tools/call",
                            {"name": "add_numbers", "arguments": {"left": 4, "right": 7}},
                        ),
                        ("resources/list", {}),
                        ("resources/read", {"uri": "fixture://marker"}),
                        ("prompts/list", {}),
                        ("prompts/get", {"name": "fixture_prompt", "arguments": {}}),
                    )
                    for index, (method, params) in enumerate(requests):
                        message: dict[str, Any] = {
                            "jsonrpc": "2.0",
                            "id": 100 + index,
                            "method": method,
                            "params": params,
                        }
                        reference = await python.post(
                            entry.mcp_path, headers=headers_python, json=message
                        )
                        candidate = await rust.post(rust_path, headers=headers_rust, json=message)
                        with self.subTest(service=entry.id, method=method):
                            self.assertEqual(candidate.status_code, reference.status_code)
                            expected = rpc(reference).get("result")
                            actual = rpc(candidate).get("result")
                            self.assertIsNotNone(expected, reference.text[:400])
                            self.assertIsNotNone(actual, candidate.text[:400])
                            # FastMCP facade's external descriptions are the contract.
                            if method == "tools/list":

                                def normalized(value: dict[str, Any]) -> dict[str, Any]:
                                    return {
                                        tool["name"]: {
                                            "description": tool.get("description"),
                                            "inputSchema": tool.get("inputSchema"),
                                            "outputSchema": tool.get("outputSchema"),
                                            "annotations": tool.get("annotations"),
                                        }
                                        for tool in value.get("tools", [])
                                    }

                                self.assertEqual(normalized(actual), normalized(expected))
                            elif method == "tools/call":
                                self.assertEqual(
                                    actual.get("structuredContent"),
                                    expected.get("structuredContent"),
                                )
                                self.assertEqual(
                                    actual.get("isError", False), expected.get("isError", False)
                                )
                            elif method in {"resources/list", "prompts/list"}:
                                field = "resources" if method == "resources/list" else "prompts"
                                self.assertEqual(actual[field], expected[field])
                            else:
                                self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
