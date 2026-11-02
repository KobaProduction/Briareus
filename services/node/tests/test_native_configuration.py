"""Native configuration separates worker authority from one-shot policy helpers."""

import unittest
from uuid import uuid4

from node_agent.docker_engine import container_config
from node_agent.network_policy import NetworkPolicy, helper_config
from test_reconciliation import fixture


class NativeConfigurationTests(unittest.TestCase):
    def test_worker_configuration_has_no_host_authority(self) -> None:
        _, spec = fixture()
        config = container_config(spec)
        host = config.host
        self.assertFalse(host.privileged)
        self.assertEqual(host.cap_drop, ["ALL"])
        self.assertEqual(host.memory, spec.limits.memory_bytes)
        self.assertEqual(host.nano_cpus, 100_000_000)
        self.assertEqual(host.pids, spec.limits.pids)
        self.assertFalse(
            {"Binds", "Devices", "PortBindings", "VolumesFrom"}
            & host.model_dump(by_alias=True, exclude_none=True).keys()
        )
        self.assertNotEqual(config.user.split(":")[0], "0")

    def test_helper_is_one_shot_netadmin_only_without_sockets_volumes_or_privileged(self) -> None:
        policy = NetworkPolicy(
            str(uuid4()), str(uuid4()), "br-123456789abc", "172.30.77.0/24", ("1.1.1.1",)
        )
        config = helper_config(policy, "registry.example/node@sha256:" + "a" * 64)
        host = config.host
        self.assertEqual(host.cap_drop, ["ALL"])
        self.assertEqual(host.cap_add, ["NET_ADMIN"])
        self.assertEqual(host.network_mode, "host")
        self.assertFalse(host.privileged)
        self.assertTrue(host.read_only)
        self.assertIsNone(host.binds)
        self.assertIsNone(host.mounts)
        self.assertNotIn("docker.sock", config.model_dump_json())
