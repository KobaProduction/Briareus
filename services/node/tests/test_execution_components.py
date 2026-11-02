"""Security and capacity boundaries of complete multi-container placements."""

import unittest
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from node_agent.application.inventory import ObserveInventory
from node_agent.docker_engine import EngineFailure, container_config, network_name
from node_agent.domain.inventory import Allocation, InventoryInvalid
from node_agent.egress_runtime import companion_config, companion_name
from node_agent.infrastructure.container_models import (
    ContainerConfiguration,
    ContainerInspection,
    ContainerSummary,
)
from node_agent.infrastructure.inventory import DockerComponentInventory, egress_quota
from node_agent.runtime_profiles import EGRESS_REQUIRED, SUPERVISOR_MODULES
from test_reconciliation import fixture

from node_protocol import Deployment, NodeRecord, ResourceLimits, WorkspaceMount
from node_protocol.network_attestation import PublicNetworkAttestation


class InspectEngine:
    def __init__(self, rows: list[ContainerInspection]) -> None:
        self.rows = rows

    async def containers(self, node: UUID) -> tuple[ContainerSummary, ...]:
        del node
        return tuple(ContainerSummary(identity=row.identity) for row in self.rows)

    async def inspect(self, identity: str) -> ContainerInspection | None:
        return next((row for row in self.rows if row.identity == identity), None)


def deployment(module: str = "web") -> tuple[NodeRecord, Deployment]:
    node, original = fixture()
    spec = original.model_copy(
        update={
            "workspace": WorkspaceMount(id=uuid4()),
            "release": original.release.model_copy(update={"module": module}),
            "limits": ResourceLimits(memory_bytes=1024 * 1024**2, cpu_millis=1000, pids=512),
            "effect_verify_key": Ed25519PrivateKey.generate()
            .public_key()
            .public_bytes(
                serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
            )
            .decode(),
        }
    )
    return node, spec


def observed_row(config: ContainerConfiguration, name: str, identity: str) -> ContainerInspection:
    return ContainerInspection.model_validate(
        {
            "Id": identity,
            "Name": "/" + name,
            "Config": config.model_dump(by_alias=True, exclude_none=True),
            "HostConfig": config.host.model_dump(by_alias=True, exclude_none=True),
            "State": {"Running": True, "Health": {"Status": "healthy"}},
        }
    )


class ExecutionComponentsTests(unittest.IsolatedAsyncioTestCase):
    def test_all_supervisors_have_only_private_socket_and_three_capabilities(self) -> None:
        for module in SUPERVISOR_MODULES:
            with self.subTest(module=module):
                _, spec = deployment(module)
                config = container_config(spec)
                host = config.host
                self.assertEqual(config.user, "0:0")
                self.assertEqual(host.cap_drop, ["ALL"])
                self.assertEqual(set(host.cap_add or []), {"SETUID", "SETGID", "KILL"})
                self.assertEqual(
                    host.binds,
                    [
                        f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway/workers/{spec.container_name}:/{module}-link:rw"
                    ],
                )
                self.assertFalse(host.privileged)
                self.assertTrue(host.read_only)
                self.assertFalse(
                    {"Devices", "PortBindings", "VolumesFrom"}
                    & host.model_dump(by_alias=True, exclude_none=True).keys()
                )
                if module in {"reverse", "radare2", "serena"}:
                    self.assertEqual(host.network_mode, "none")

    def test_egress_has_no_secret_or_project_mount_and_quota_is_included(self) -> None:
        _, spec = deployment()
        main = container_config(spec)
        peer = companion_config(spec, "registry.example/node@sha256:" + "a" * 64)
        self.assertEqual(main.host.memory + peer.host.memory, spec.limits.memory_bytes)
        self.assertEqual(main.host.memory_swap + peer.host.memory_swap, spec.limits.memory_bytes)
        self.assertEqual(
            main.host.nano_cpus + peer.host.nano_cpus, spec.limits.cpu_millis * 1_000_000
        )
        self.assertEqual(main.host.pids + peer.host.pids, spec.limits.pids)
        self.assertFalse(
            {"Binds", "Mounts", "PortBindings", "Devices"}
            & peer.host.model_dump(by_alias=True, exclude_none=True).keys()
        )
        self.assertIsNone(peer.environment)
        self.assertEqual(peer.user, "1000:1000")
        assert main.host.mounts is not None
        self.assertEqual(main.host.mounts[0].target, "/browser")
        self.assertIsNone(peer.host.cap_add)

    async def test_components_are_one_allocation_and_missing_egress_is_not_ready(self) -> None:
        node, spec = deployment()
        main = observed_row(container_config(spec), spec.container_name, "a" * 64)
        peer = observed_row(
            companion_config(spec, "registry.example/node@sha256:" + "b" * 64),
            companion_name(spec.container_name),
            "b" * 64,
        )
        engine = InspectEngine([main, peer])
        observe = ObserveInventory(DockerComponentInventory(engine), egress_quota())
        result = await observe.execute(node.id)
        self.assertEqual(len(result), 1)
        expected = Allocation(spec.limits.memory_bytes, spec.limits.cpu_millis, spec.limits.pids)
        self.assertEqual(result[0].allocation, expected)
        self.assertTrue(result[0].ready)
        engine.rows = [main]
        result = await observe.execute(node.id)
        self.assertEqual(result[0].allocation, expected)
        self.assertFalse(result[0].ready)

    async def test_foreign_revision_and_unbounded_helper_fail_closed(self) -> None:
        node, spec = deployment()
        main = observed_row(container_config(spec), spec.container_name, "a" * 64)
        peer = observed_row(
            companion_config(spec, "registry.example/node@sha256:" + "b" * 64),
            companion_name(spec.container_name),
            "b" * 64,
        )
        foreign = peer.model_copy(deep=True)
        foreign.config.labels["io.briareus.spec"] = "c" * 64
        mounted = peer.model_copy(deep=True)
        mounted.host.binds = ["/host:/secret"]
        unbounded = peer.model_copy(deep=True)
        unbounded.host.memory = 1
        for changed in (foreign, mounted, unbounded):
            with self.assertRaises(InventoryInvalid):
                await ObserveInventory(
                    DockerComponentInventory(InspectEngine([main, changed])), egress_quota()
                ).execute(node.id)

    async def test_orphan_helper_remains_accounted_and_unready(self) -> None:
        node, spec = deployment()
        peer = observed_row(
            companion_config(spec, "registry.example/node@sha256:" + "b" * 64),
            companion_name(spec.container_name),
            "b" * 64,
        )
        result = await ObserveInventory(
            DockerComponentInventory(InspectEngine([peer])), egress_quota()
        ).execute(node.id)
        self.assertEqual(len(result), 1)
        self.assertFalse(result[0].ready)
        self.assertGreater(result[0].allocation.memory_bytes, 0)

    def test_old_readonly_files_and_offline_terminal_budgets_remain_unchanged(self) -> None:
        _, spec = fixture()
        files = container_config(spec)
        self.assertNotIn(EGRESS_REQUIRED, files.labels)
        _, terminal = deployment("terminal")
        terminal = terminal.model_copy(
            update={"limits": ResourceLimits(memory_bytes=256 * 1024**2, cpu_millis=200, pids=64)}
        )
        config = container_config(terminal)
        self.assertEqual(config.host.network_mode, "none")
        self.assertEqual(config.host.memory, terminal.limits.memory_bytes)


class ConfigurationWireTests(unittest.TestCase):
    def test_all_modules_roundtrip_and_configuration_is_fingerprinted(self) -> None:
        from node_protocol.grpc_codec import decode_deployment, encode_deployment
        from node_protocol.models import (
            BrowserConfiguration,
            ModuleConfiguration,
            SerenaConfiguration,
        )

        for module in ("files", *sorted(SUPERVISOR_MODULES)):
            _, spec = deployment(module)
            if module == "web":
                spec = spec.model_copy(
                    update={
                        "configuration": ModuleConfiguration(
                            browser=BrowserConfiguration(developer_access_enabled=True)
                        )
                    }
                )
            if module == "serena":
                spec = spec.model_copy(
                    update={
                        "configuration": ModuleConfiguration(
                            serena=SerenaConfiguration(project_path="src")
                        )
                    }
                )
            result = decode_deployment(encode_deployment(spec))
            self.assertEqual(result, spec)
            self.assertEqual(result.fingerprint, spec.fingerprint)
            if spec.configuration:
                self.assertNotEqual(
                    spec.fingerprint, spec.model_copy(update={"configuration": None}).fingerprint
                )

    def test_direct_network_is_explicit_and_does_not_change_existing_configuration_wire(
        self,
    ) -> None:
        from node_agent.runtime_profiles import uses_direct_network

        from node_protocol.grpc_codec import decode_deployment, encode_deployment
        from node_protocol.models import (
            BrowserConfiguration,
            ModuleConfiguration,
            NetworkConfiguration,
        )

        _, terminal = deployment("terminal")
        self.assertFalse(uses_direct_network(terminal))
        direct = terminal.model_copy(
            update={"configuration": ModuleConfiguration(network=NetworkConfiguration())}
        )
        self.assertTrue(uses_direct_network(direct))
        self.assertEqual(decode_deployment(encode_deployment(direct)), direct)
        with self.assertRaises(EngineFailure):
            container_config(direct)
        browser = ModuleConfiguration(browser=BrowserConfiguration())
        self.assertNotIn("network", browser.model_dump())
        self.assertIn("serena", browser.model_dump())

    def test_verified_direct_config_has_no_proxy_and_no_firewall_capability(self) -> None:
        from node_protocol.models import ModuleConfiguration, NetworkConfiguration

        _, spec = deployment("terminal")
        spec = spec.model_copy(
            update={"configuration": ModuleConfiguration(network=NetworkConfiguration())}
        )
        proof = PublicNetworkAttestation(
            profile="public",
            node_uuid=spec.node_uuid,
            project_uuid=spec.project_uuid,
            placement_uuid=spec.id,
            fingerprint=spec.fingerprint,
            ready=True,
            policy_sha256="a" * 64,
            subnet="10.64.1.0/24",
            gateway="10.64.1.1",
            dns=["127.0.0.11"],
            bridge="br-123456789abc",
        )
        config = container_config(spec, network_policy=proof)
        self.assertEqual(config.host.network_mode, network_name(spec) + "-public")
        self.assertNotIn("NET_ADMIN", config.host.cap_add or [])
        self.assertFalse(any("PROXY=" in item for item in config.environment or []))
        self.assertNotIn(EGRESS_REQUIRED, config.labels)
        for key in ("fingerprint", "node_uuid", "placement_uuid", "project_uuid"):
            with self.assertRaises(EngineFailure):
                container_config(spec, network_policy=proof.model_copy(update={key: "foreign"}))

    def test_legacy_wire_omits_empty_new_field(self) -> None:
        _, spec = fixture()
        self.assertNotIn("configuration", spec.model_dump())
        from node_protocol.grpc_codec import decode_deployment, encode_deployment

        self.assertFalse(encode_deployment(spec).HasField("configuration"))
        self.assertEqual(decode_deployment(encode_deployment(spec)).fingerprint, spec.fingerprint)
