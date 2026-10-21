"""Node bridges must never shadow the configured Core or registry address."""
import ipaddress
import unittest
from types import SimpleNamespace

from node_agent.docker_engine import EngineFailure
from node_agent.network_addressing import bridge_ipam, validate_network_addresses


class AddressingTests(unittest.IsolatedAsyncioTestCase):
    def engine(self, networks=()):
        async def request(*args, **kwargs):
            return SimpleNamespace(json=lambda:list(networks))
        return SimpleNamespace(control_addresses=("172.25.80.1", "10.100.1.8"),
            allowed_registries=frozenset({"172.25.80.1:5500"}), request=request)

    async def test_explicit_small_subnet_excludes_existing_networks_and_control(self):
        engine = self.engine([{"IPAM":{"Config":[{"Subnet":"10.64.0.0/16"}]}}])
        for name in ("gateway", "files", "terminal", "web-egress"):
            result = await bridge_ipam(engine,name)
            subnet = ipaddress.ip_network(result["Config"][0]["Subnet"])
            self.assertEqual(subnet.prefixlen,24)
            self.assertFalse(subnet.overlaps(ipaddress.ip_network("10.64.0.0/16")))
            self.assertTrue(all(ipaddress.ip_address(value) not in subnet for value in engine.control_addresses))
            self.assertEqual(result,await bridge_ipam(engine,name))

    def test_existing_registry_collision_is_rejected(self):
        with self.assertRaises(EngineFailure):
            validate_network_addresses(self.engine(),{"IPAM":{"Config":[{"Subnet":"172.25.0.0/16"}]}})

    async def test_pool_exhaustion_fails_closed(self):
        engine = self.engine([{"IPAM":{"Config":[{"Subnet":"10.0.0.0/8"}]}}])
        with self.assertRaises(EngineFailure):
            await bridge_ipam(engine,"no-free-addresses")
