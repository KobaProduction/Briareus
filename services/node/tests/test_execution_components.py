"""Security and capacity boundaries of complete multi-container placements."""
import copy
import unittest
from uuid import uuid4
from node_protocol import WorkspaceMount, ResourceLimits
from node_agent.controller import Controller
from node_agent.docker_engine import container_config, labels, network_name, EngineFailure
from node_agent.egress_runtime import companion_config, companion_name
from node_agent.runtime_profiles import SUPERVISOR_MODULES, EGRESS_REQUIRED, ROLE_LABEL
from test_reconciliation import fixture


class InspectEngine:
    def __init__(self, rows):
        self.rows = rows
    async def containers(self, node):
        return [{"Id":row["Id"]} for row in self.rows]
    async def inspect(self, identity):
        return next(row for row in self.rows if row["Id"]==identity)


def deployment(module="web"):
    node, original = fixture()
    spec = original.model_copy(update={"workspace":WorkspaceMount(id=uuid4()),
        "release":original.release.model_copy(update={"module":module}),
        "limits":ResourceLimits(memory_bytes=1024*1024**2,cpu_millis=1000,pids=512),
        "effect_verify_key":__import__("cryptography.hazmat.primitives.asymmetric.ed25519",fromlist=["Ed25519PrivateKey"]).Ed25519PrivateKey.generate().public_key().public_bytes(
            __import__("cryptography.hazmat.primitives.serialization",fromlist=["Encoding"]).Encoding.PEM,
            __import__("cryptography.hazmat.primitives.serialization",fromlist=["PublicFormat"]).PublicFormat.SubjectPublicKeyInfo).decode()})
    return node,spec


def observed_row(config, name, identity):
    return {"Id":identity,"Name":"/"+name,"Config":config,"HostConfig":config["HostConfig"],
        "State":{"Running":True,"Health":{"Status":"healthy"}}}


class ExecutionComponentsTests(unittest.IsolatedAsyncioTestCase):
    def test_all_supervisors_have_only_private_socket_and_three_capabilities(self):
        for module in SUPERVISOR_MODULES:
            with self.subTest(module=module):
                _,spec = deployment(module)
                config = container_config(spec)
                host = config["HostConfig"]
                self.assertEqual(config["User"],"0:0")
                self.assertEqual(host["CapDrop"],["ALL"])
                self.assertEqual(set(host["CapAdd"]),{"SETUID","SETGID","KILL"})
                self.assertEqual(host["Binds"],[f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway/workers/{spec.container_name}:/{module}-link:rw"])
                self.assertFalse(host["Privileged"])
                self.assertTrue(host["ReadonlyRootfs"])
                self.assertFalse({"Devices","PortBindings","VolumesFrom"}&host.keys())
                if module in {"reverse","radare2","serena"}:
                    self.assertEqual(host["NetworkMode"],"none")

    def test_egress_has_no_secret_or_project_mount_and_quota_is_included(self):
        _,spec = deployment()
        main = container_config(spec)
        peer = companion_config(spec,"registry.example/node@sha256:"+"a"*64)
        for key in ("Memory","MemorySwap","NanoCpus","PidsLimit"):
            actual = main["HostConfig"][key]+peer["HostConfig"][key]
            expected = {"Memory":spec.limits.memory_bytes,"MemorySwap":spec.limits.memory_bytes,
                "NanoCpus":spec.limits.cpu_millis*1_000_000,"PidsLimit":spec.limits.pids}[key]
            self.assertEqual(actual,expected)
        self.assertFalse({"Binds","Mounts","PortBindings","Devices"}&peer["HostConfig"].keys())
        self.assertNotIn("Env",peer)
        self.assertEqual(peer["User"],"1000:1000")
        self.assertEqual(main["HostConfig"]["Mounts"][0]["Target"],"/browser")
        self.assertNotIn("CapAdd",peer["HostConfig"])

    async def test_components_are_one_allocation_and_missing_egress_is_not_ready(self):
        node,spec = deployment()
        main = observed_row(container_config(spec),spec.container_name,"a"*64)
        peer = observed_row(companion_config(spec,"registry.example/node@sha256:"+"b"*64),
                            companion_name(spec.container_name),"b"*64)
        controller = Controller(node,InspectEngine([main,peer]),None)
        result = await controller.observed()
        self.assertEqual(len(result),1)
        self.assertEqual(result[0].limits,spec.limits)
        self.assertTrue(result[0].ready)
        controller.engine.rows = [main]
        result = await controller.observed()
        self.assertEqual(result[0].limits,spec.limits)
        self.assertFalse(result[0].ready)

    async def test_foreign_revision_and_unbounded_helper_fail_closed(self):
        node,spec = deployment()
        main = observed_row(container_config(spec),spec.container_name,"a"*64)
        peer = observed_row(companion_config(spec,"registry.example/node@sha256:"+"b"*64),
                            companion_name(spec.container_name),"b"*64)
        for mutate in (lambda p:p["Config"]["Labels"].update({"io.briareus.spec":"c"*64}),
                       lambda p:p["HostConfig"].update({"Binds":["/host:/secret"]}),
                       lambda p:p["HostConfig"].update({"Memory":1})):
            changed = copy.deepcopy(peer)
            mutate(changed)
            with self.assertRaises(EngineFailure):
                await Controller(node,InspectEngine([main,changed]),None).observed()

    async def test_orphan_helper_remains_accounted_and_unready(self):
        node,spec = deployment()
        peer = observed_row(companion_config(spec,"registry.example/node@sha256:"+"b"*64),
                            companion_name(spec.container_name),"b"*64)
        result = await Controller(node,InspectEngine([peer]),None).observed()
        self.assertEqual(len(result),1)
        self.assertFalse(result[0].ready)
        self.assertGreater(result[0].limits.memory_bytes,0)

    def test_old_readonly_files_and_offline_terminal_budgets_remain_unchanged(self):
        _,spec = fixture()
        files = container_config(spec)
        self.assertNotIn(EGRESS_REQUIRED,files["Labels"])
        _,terminal = deployment("terminal")
        terminal = terminal.model_copy(update={"limits":ResourceLimits(memory_bytes=256*1024**2,cpu_millis=200,pids=64)})
        config = container_config(terminal)
        self.assertEqual(config["HostConfig"]["NetworkMode"],"none")
        self.assertEqual(config["HostConfig"]["Memory"],terminal.limits.memory_bytes)


class ConfigurationWireTests(unittest.TestCase):
    def test_all_modules_roundtrip_and_configuration_is_fingerprinted(self):
        from node_protocol.grpc_codec import encode_deployment,decode_deployment
        from node_protocol.models import ModuleConfiguration,BrowserConfiguration,SerenaConfiguration
        for module in ("files",*sorted(SUPERVISOR_MODULES)):
            _,spec=deployment(module)
            if module=="web":
                spec=spec.model_copy(update={"configuration":ModuleConfiguration(browser=BrowserConfiguration(developer_access_enabled=True))})
            if module=="serena":
                spec=spec.model_copy(update={"configuration":ModuleConfiguration(serena=SerenaConfiguration(project_path="src"))})
            result=decode_deployment(encode_deployment(spec))
            self.assertEqual(result,spec)
            self.assertEqual(result.fingerprint,spec.fingerprint)
            if spec.configuration:
                self.assertNotEqual(spec.fingerprint,spec.model_copy(update={"configuration":None}).fingerprint)

    def test_direct_network_is_explicit_and_does_not_change_existing_configuration_wire(self):
        from node_protocol.grpc_codec import encode_deployment,decode_deployment
        from node_protocol.models import ModuleConfiguration,NetworkConfiguration,BrowserConfiguration
        from node_agent.runtime_profiles import uses_direct_network
        _,terminal=deployment("terminal")
        self.assertFalse(uses_direct_network(terminal))
        direct=terminal.model_copy(update={"configuration":ModuleConfiguration(network=NetworkConfiguration())})
        self.assertTrue(uses_direct_network(direct))
        self.assertEqual(decode_deployment(encode_deployment(direct)),direct)
        with self.assertRaises(EngineFailure):
            container_config(direct)
        browser=ModuleConfiguration(browser=BrowserConfiguration())
        self.assertNotIn("network",browser.model_dump())
        self.assertIn("serena",browser.model_dump())

    def test_verified_direct_config_has_no_proxy_and_no_firewall_capability(self):
        from node_protocol.models import ModuleConfiguration,NetworkConfiguration
        _,spec=deployment("terminal")
        spec=spec.model_copy(update={"configuration":ModuleConfiguration(network=NetworkConfiguration())})
        proof={"profile":"public","node_uuid":str(spec.node_uuid),"project_uuid":str(spec.project_uuid),
            "placement_uuid":str(spec.id),"fingerprint":spec.fingerprint,"ready":True,"policy_sha256":"a"*64}
        config=container_config(spec,network_policy=proof)
        self.assertEqual(config["HostConfig"]["NetworkMode"],network_name(spec)+"-public")
        self.assertNotIn("NET_ADMIN",config["HostConfig"]["CapAdd"])
        self.assertFalse(any("PROXY=" in item for item in config.get("Env",[])))
        self.assertNotIn(EGRESS_REQUIRED,config["Labels"])
        for key in ("fingerprint","node_uuid","placement_uuid","project_uuid"):
            with self.assertRaises(EngineFailure):
                container_config(spec,network_policy={**proof,key:"foreign"})

    def test_legacy_wire_omits_empty_new_field(self):
        _,spec=fixture()
        self.assertNotIn("configuration",spec.model_dump())
        from node_protocol.grpc_codec import encode_deployment,decode_deployment
        self.assertFalse(encode_deployment(spec).HasField("configuration"))
        self.assertEqual(decode_deployment(encode_deployment(spec)).fingerprint,spec.fingerprint)
