from __future__ import annotations

import unittest
from unittest.mock import MagicMock

import httpx
from briareus_service_catalog import ServiceDefinition, service_definition
from briareus_service_discovery import ServiceDiscovery, ServiceRegistry
from pydantic import ValidationError


class ServiceDiscoveryContracts(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.github = service_definition("github")
        self.custom = ServiceDefinition(id="new-provider", name="New Provider", group="custom")
        self.live = {self.github.id: self.github, self.custom.id: self.custom}
        self.requests: list[str] = []
        self.registry = MagicMock(spec=ServiceRegistry)
        self.registry.environment = "test"
        self.registry.inventory.return_value = (self.custom,)
        self.registry.active_services.side_effect = lambda: frozenset(self.live)

        async def respond(request: httpx.Request) -> httpx.Response:
            self.requests.append(str(request.url))
            service = self.live.get(request.url.host)
            if service is None:
                return httpx.Response(503)
            return httpx.Response(
                200, json={"service": service.model_dump(), "environment": "test", "ready": True}
            )

        self.discovery = ServiceDiscovery(
            self.registry,
            client=httpx.AsyncClient(transport=httpx.MockTransport(respond)),
        )

    async def asyncTearDown(self) -> None:
        await self.discovery.close()

    async def test_network_presence_controls_visibility_and_reconnect_without_restart(self) -> None:
        first = await self.discovery.snapshot()
        connected = {service.id for service in first.services if service.connected}
        self.assertEqual(connected, {"github", "new-provider"})
        self.assertIn("ghidra", {service.id for service in first.services if not service.connected})
        del self.live["github"]
        stopped = await self.discovery.snapshot(refresh=True)
        self.assertFalse(
            next(service.connected for service in stopped.services if service.id == "github")
        )
        self.live["github"] = self.github
        restarted = await self.discovery.snapshot(refresh=True)
        self.assertTrue(
            next(service.connected for service in restarted.services if service.id == "github")
        )

    async def test_registered_unknown_provider_gets_its_own_grouped_mcp_path(self) -> None:
        snapshot = await self.discovery.snapshot()
        service = next(service for service in snapshot.services if service.id == "new-provider")
        self.assertEqual(service.mcp_path, "/custom/new-provider/mcp")
        self.assertEqual(service.group, "custom")
        before = len(self.requests)
        self.assertEqual(await self.discovery.snapshot(), snapshot)
        self.assertEqual(len(self.requests), before)

    async def test_wrong_provider_identity_on_a_dns_endpoint_is_not_connected(self) -> None:
        self.live["github"] = service_definition("signoz")
        snapshot = await self.discovery.snapshot()
        self.assertFalse(
            next(service.connected for service in snapshot.services if service.id == "github")
        )

    def test_service_identity_cannot_inject_an_external_probe_url(self) -> None:
        for value in ("https://outside.example", "127.0.0.1", "../../admin", "provider@outside"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                ServiceDefinition(id=value, name="Invalid", group="web")
        for group in ("api", "admin", "health"):
            with self.subTest(group=group), self.assertRaises(ValidationError):
                ServiceDefinition(id="provider", name="Provider", group=group)

    async def test_a_provider_without_this_environment_membership_is_not_probed(self) -> None:
        self.registry.active_services.side_effect = None
        self.registry.active_services.return_value = frozenset()
        snapshot = await self.discovery.snapshot()
        self.assertFalse(any(service.connected for service in snapshot.services))
        self.assertEqual(self.requests, [])
