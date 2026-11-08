from __future__ import annotations

import json
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import httpx
from briareus_json_values import JsonObject, json_array, json_object
from briareus_service_catalog import ServiceDefinition, service_definition
from briareus_service_discovery import DiscoveredService, DiscoverySnapshot, ServiceDiscovery
from fastmcp import FastMCP
from gateway.gateway_settings import GatewayAuthSettings
from gateway.service_routes import ServiceMcpRoutes
from gateway.settings import GatewaySettings
from starlette.applications import Starlette
from starlette.routing import Mount
from zitadel_test_support import ZitadelTokenFixture


def _present(service: ServiceDefinition, *, connected: bool = True) -> DiscoveredService:
    return DiscoveredService(
        id=service.id,
        name=service.name,
        group=service.group,
        mcp_path=service.mcp_path,
        connected=connected,
    )


def _rpc(response: httpx.Response) -> JsonObject:
    if response.headers.get("content-type", "").startswith("application/json"):
        return json_object(response.json(), context="MCP response")
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json_object(json.loads(line[6:]), context="MCP SSE response")
    raise AssertionError(f"Missing MCP response status={response.status_code}")


async def _timeout() -> float:
    return 5.0


class IndividualMcpContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.github = service_definition("github")
        self.signoz = service_definition("signoz")
        self.services = [_present(self.github), _present(self.signoz)]
        self.discovery = MagicMock(spec=ServiceDiscovery)

        async def snapshot() -> DiscoverySnapshot:
            return DiscoverySnapshot(services=tuple(self.services), checked_at=datetime.now(UTC))

        self.discovery.snapshot = AsyncMock(side_effect=snapshot)
        github: FastMCP[None] = FastMCP("GitHub")
        signoz: FastMCP[None] = FastMCP("SigNoz")

        @github.tool
        def github_only() -> str:
            return "GitHub response"

        @signoz.tool
        def signoz_only() -> str:
            return "SigNoz response"

        self.targets = {"github": github, "signoz": signoz}
        self.fixture = ZitadelTokenFixture()
        self.routes = ServiceMcpRoutes(
            self.discovery,
            GatewaySettings(),
            GatewayAuthSettings(
                **self.fixture.settings.model_dump(),
                enabled=True,
                public_base_url="http://localhost:18080",
            ),
            _timeout,
            targets=self.targets,
        )
        self.lifespan = self.routes.lifespan()
        await self.lifespan.__aenter__()
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(Starlette(routes=[Mount("/", self.routes)])),
            base_url="http://localhost:18080",
        )

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        await self.lifespan.__aexit__(None, None, None)
        self.fixture.close()

    async def _initialize(self, path: str) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/event-stream",
            "Authorization": "Bearer " + self.fixture.token(),
        }
        response = await self.client.post(
            path,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "individual-service-contract", "version": "1"},
                },
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("result", _rpc(response))
        if "mcp-session-id" in response.headers:
            headers["Mcp-Session-Id"] = response.headers["mcp-session-id"]
        await self.client.post(
            path,
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )
        return headers

    async def test_each_provider_has_an_isolated_authenticated_tool_catalog(self) -> None:
        for service, expected in [(self.github, "github_only"), (self.signoz, "signoz_only")]:
            headers = await self._initialize(service.mcp_path)
            response = await self.client.post(
                service.mcp_path,
                headers=headers,
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                },
            )
            self.assertEqual(response.status_code, 200)
            result = json_object(_rpc(response)["result"], context="tool catalog")
            tools = json_array(result["tools"], context="provider tools")
            self.assertEqual(
                [json_object(tool, context="tool")["name"] for tool in tools], [expected]
            )
        for removed in ("/mcp", "/web/mcp", "/observability/mcp"):
            self.assertEqual((await self.client.get(removed)).status_code, 404)

    async def test_unavailable_provider_is_not_forwarded_and_other_provider_stays_available(
        self,
    ) -> None:
        self.services[0] = _present(self.github, connected=False)
        response = await self.client.post(self.github.mcp_path, json={})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["code"], "service_unavailable")
        await self._initialize(self.signoz.mcp_path)

    async def test_registered_provider_gets_a_route_without_gateway_restart(self) -> None:
        custom = ServiceDefinition(id="custom-provider", name="Custom Provider", group="plugins")
        backend: FastMCP[None] = FastMCP("Custom Provider")

        @backend.tool
        def custom_only() -> str:
            return "custom"

        self.targets[custom.id] = backend
        self.services.append(_present(custom))
        await self._initialize(custom.mcp_path)

    async def test_provider_metadata_and_challenge_identify_its_own_resource(self) -> None:
        for service in (self.github, self.signoz):
            response = await self.client.get(service.mcp_path)
            self.assertEqual(response.status_code, 401)
            metadata_path = "/.well-known/oauth-protected-resource" + service.mcp_path
            self.assertIn(metadata_path, response.headers["www-authenticate"])
            metadata = await self.client.get(metadata_path)
            self.assertEqual(metadata.status_code, 200)
            self.assertEqual(
                metadata.json()["resource"], "http://localhost:18080" + service.mcp_path
            )
            self.assertEqual(
                metadata.json()["authorization_servers"], [self.fixture.settings.issuer_url]
            )
