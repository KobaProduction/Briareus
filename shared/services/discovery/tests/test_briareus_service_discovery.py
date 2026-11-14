from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import httpx
import valkey
from briareus_hand_runtime.runtime_common import private_http_app
from briareus_hand_runtime.settings import PrivateRuntimeSettings
from briareus_service_catalog import ServiceDefinition, service_definition
from briareus_service_discovery import ServiceDiscovery, ServiceRegistry
from fastmcp import FastMCP
from pydantic import ValidationError
from starlette.applications import Starlette


class ServiceRegistrationReliabilityContracts(unittest.TestCase):
    def make_registry(self, **overrides: str) -> tuple[ServiceRegistry, MagicMock]:
        variables = {"DEPLOYMENT_ENVIRONMENT": "test", "VALKEY_PASSWORD": "fixture"}
        variables.update(overrides)
        client = MagicMock()
        with (
            patch.dict(os.environ, variables, clear=True),
            patch(
                "briareus_service_discovery._registry.valkey.Valkey.from_url",
                return_value=client,
            ) as from_url,
        ):
            registry = ServiceRegistry()
        self.assertEqual(
            from_url.call_args.kwargs["socket_connect_timeout"],
            float(overrides.get("VALKEY_REGISTRY_CONNECT_TIMEOUT_SECONDS", "1")),
        )
        self.assertEqual(
            from_url.call_args.kwargs["socket_timeout"],
            float(overrides.get("VALKEY_REGISTRY_SOCKET_TIMEOUT_SECONDS", "1")),
        )
        self.assertEqual(from_url.call_args.kwargs["health_check_interval"], 30)
        return registry, client

    def test_short_transient_failures_do_not_emit_warning_alerts(self) -> None:
        registry, client = self.make_registry()
        pipeline = client.pipeline.return_value.__enter__.return_value
        pipeline.execute.side_effect = [
            valkey.exceptions.TimeoutError("private-sentinel"),
            valkey.exceptions.TimeoutError("private-sentinel"),
            valkey.exceptions.TimeoutError("private-sentinel"),
            [True, True],
        ]
        with (
            patch(
                "briareus_service_discovery._registry.time.monotonic",
                side_effect=[100, 105, 110, 114],
            ),
            self.assertLogs("briareus_service_discovery._registry", level="DEBUG") as logs,
        ):
            for _ in range(4):
                registry.announce(service_definition("github"), "test-instance")
        self.assertEqual(
            [line for line in logs.output if "WARNING" in line], []
        )
        recovered = [line for line in logs.output if "registration recovered" in line]
        self.assertEqual(len(recovered), 1)
        self.assertIn("failed_attempts=3", recovered[0])
        self.assertNotIn("private-sentinel", str(logs.output))
        self.assertEqual(pipeline.set.call_count, 8)
        self.assertEqual(pipeline.execute.call_count, 4)
        client.pipeline.assert_called_with(transaction=False)

    def test_sustained_failure_warns_once_per_interval_and_recovers(self) -> None:
        registry, client = self.make_registry(
            VALKEY_REGISTRY_FAILURE_GRACE_SECONDS="15",
            VALKEY_REGISTRY_WARNING_INTERVAL_SECONDS="60",
        )
        pipeline = client.pipeline.return_value.__enter__.return_value
        pipeline.execute.side_effect = [
            valkey.exceptions.ConnectionError("private-sentinel"),
        ] * 5 + [[True, True]]
        with (
            patch(
                "briareus_service_discovery._registry.time.monotonic",
                side_effect=[100, 105, 115, 120, 180, 190],
            ),
            self.assertLogs("briareus_service_discovery._registry", level="DEBUG") as logs,
        ):
            for _ in range(6):
                registry.announce(service_definition("server"), "test-instance")
        warnings = [line for line in logs.output if "WARNING" in line]
        self.assertEqual(len(warnings), 2)
        self.assertTrue(all("reason=ConnectionError" in line for line in warnings))
        self.assertIn("outage_seconds=15.0", warnings[0])
        self.assertIn("outage_seconds=80.0", warnings[1])
        self.assertNotIn("private-sentinel", str(logs.output))
        self.assertEqual(len([x for x in logs.output if "registration recovered" in x]), 1)

    def test_configurable_registry_timeouts_do_not_modify_cache_defaults(self) -> None:
        registry, client = self.make_registry(
            VALKEY_REGISTRY_CONNECT_TIMEOUT_SECONDS="2",
            VALKEY_REGISTRY_SOCKET_TIMEOUT_SECONDS="3",
        )
        self.assertIsNotNone(registry.client)
        self.assertIs(client, registry.client)
        with (
            patch.dict(
                os.environ,
                {"DEPLOYMENT_ENVIRONMENT": "test", "VALKEY_PASSWORD": "fixture",
                 "VALKEY_REGISTRY_CONNECT_TIMEOUT_SECONDS": "2",
                 "VALKEY_REGISTRY_SOCKET_TIMEOUT_SECONDS": "3"},
                clear=True,
            ),
            patch("briareus_service_discovery._registry.valkey.Valkey.from_url") as from_url,
        ):
            ServiceRegistry()
        self.assertEqual(from_url.call_args.kwargs["socket_connect_timeout"], 2.0)
        self.assertEqual(from_url.call_args.kwargs["socket_timeout"], 3.0)


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
            service = next(
                (
                    value
                    for key, value in self.live.items()
                    if request.url.host == f"{key}-mcp-hand"
                ),
                None,
            )
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

    def test_private_dns_is_distinct_from_public_service_identity(self) -> None:
        self.assertEqual(self.github.internal_host, "github-mcp-hand")
        self.assertEqual(self.github.internal_origin, "http://github-mcp-hand:8000")
        self.assertEqual(self.github.mcp_path, "/svc/github/mcp")
        self.assertEqual(self.custom.internal_origin, "http://new-provider-mcp-hand:8000")

    def test_private_runtime_allows_its_own_dns_without_bare_service_aliases(self) -> None:
        settings = PrivateRuntimeSettings()
        mcp = MagicMock(spec=FastMCP)
        mcp.name = "coolify"
        app = Starlette()
        mcp.http_app.return_value = app
        with patch(
            "briareus_hand_runtime.runtime_common.attach_service_discovery", return_value=app
        ):
            self.assertIs(private_http_app(mcp, settings), app)
        hosts = mcp.http_app.call_args.kwargs["allowed_hosts"]
        self.assertIn("coolify-mcp-hand:*", hosts)
        for host in ("coolify:*", "github:*", "server:*", "web:*", "ghidra:*"):
            self.assertNotIn(host, hosts)

    def test_service_identity_reserves_dns_suffix_space(self) -> None:
        longest = ServiceDefinition(id="a" * 54, name="Longest", group="custom")
        self.assertEqual(len(longest.internal_host), 63)
        with self.assertRaises(ValidationError):
            ServiceDefinition(id="a" * 55, name="Too long", group="custom")

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
