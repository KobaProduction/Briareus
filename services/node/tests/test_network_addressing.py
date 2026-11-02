"""Node bridges must never shadow the configured Core or registry address."""

import ipaddress
import unittest

import httpx
from node_agent.docker_engine import EngineFailure
from node_agent.infrastructure.container_models import ContainerConfiguration
from node_agent.infrastructure.docker_commands import (
    NetworkConnect,
    NetworkCreate,
    NetworkIpam,
    VolumeCreate,
)
from node_agent.network_addressing import bridge_ipam, validate_network_addresses


class AddressingFixture:
    control_addresses: tuple[str, ...] = ("172.25.80.1", "10.100.1.8")
    allowed_registries: frozenset[str] = frozenset({"172.25.80.1:5500"})

    def __init__(self, networks_json: str = "[]") -> None:
        self.networks_json = networks_json

    async def request(
        self,
        method: str,
        path: str,
        *,
        accepted: tuple[int, ...] = (200,),
        params: dict[str, str | int] | None = None,
        payload: ContainerConfiguration
        | NetworkCreate
        | NetworkConnect
        | VolumeCreate
        | None = None,
    ) -> httpx.Response:
        if (method, path, accepted, params, payload) != ("GET", "/networks", (200,), None, None):
            raise AssertionError("Address planning must only inspect existing networks")
        return httpx.Response(200, content=self.networks_json)


class AddressingTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_small_subnet_excludes_existing_networks_and_control(self) -> None:
        engine = AddressingFixture('[{"IPAM":{"Config":[{"Subnet":"10.64.0.0/16"}]}}]')
        for name in ("gateway", "files", "terminal", "web-egress"):
            result = await bridge_ipam(engine, name)
            assert result.configs is not None
            subnet = ipaddress.ip_network(result.configs[0].subnet)
            self.assertEqual(subnet.prefixlen, 24)
            self.assertFalse(subnet.overlaps(ipaddress.ip_network("10.64.0.0/16")))
            self.assertTrue(
                all(ipaddress.ip_address(value) not in subnet for value in engine.control_addresses)
            )
            self.assertEqual(result, await bridge_ipam(engine, name))

    def test_existing_registry_collision_is_rejected(self) -> None:
        with self.assertRaises(EngineFailure):
            validate_network_addresses(
                AddressingFixture(),
                NetworkIpam.model_validate_json('{"Config":[{"Subnet":"172.25.0.0/16"}]}'),
            )

    async def test_pool_exhaustion_fails_closed(self) -> None:
        engine = AddressingFixture('[{"IPAM":{"Config":[{"Subnet":"10.0.0.0/8"}]}}]')
        with self.assertRaises(EngineFailure):
            await bridge_ipam(engine, "no-free-addresses")
