"""Disposable engine model: policy precedes workers; private proof is immutable."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
from node_protocol.naming import worker_name
from node_agent.docker_engine import EngineFailure, network_name, labels, NODE_LABEL, DEPLOYMENT_LABEL
from node_agent.network_policy_runtime import prepare_direct_network, _json_log, _helper, recover_network_policy_helpers
from node_agent.network_policy import NetworkPolicy, helper_config, helper_name
from node_agent.workspace_init import initialize_runtime, validate_attestation
from node_agent.workspace_runtime import initializer_config
from test_reconciliation import fixture


class Engine:
    utility_image = "registry.test/node@sha256:" + "a"*64
    control_addresses = ("127.0.0.1", "1.1.1.1")
    def __init__(self, spec, running=False):
        self.spec = spec
        self.calls = []
        self.network = {"Name":network_name(spec)+"-public", "Id":"b"*64,
            "Driver":"bridge", "Internal":False, "EnableIPv6":False, "Options":{},
            "Labels":{NODE_LABEL:str(spec.node_uuid),DEPLOYMENT_LABEL:str(spec.id),"io.briareus.role":"public-execution"},
            "IPAM":{"Driver":"default","Config":[{"Subnet":"172.30.0.0/24","Gateway":"172.30.0.1"}]},
            "Containers":{"c"*64:{"Name":spec.container_name}} if running else {}}
    async def request(self, method, path, **kwargs):
        self.calls.append((method,path,kwargs))
        if path == "/info":
            return httpx.Response(200,json={"ServerVersion":"28.3.2","SecurityOptions":["name=rootless"]})
        if path.startswith("/networks/"):
            return httpx.Response(200,json=self.network)
        if path.endswith("/stop"):
            return httpx.Response(204)
        raise AssertionError(path)
    async def inspect(self, cid):
        return {"Config":{"Labels":labels(self.spec)}}


class HelperEngine:
    utility_image = Engine.utility_image
    def __init__(self):
        self.helper = None
        self.calls = []
        self.exit_code = 0
    async def inspect(self, container):
        return self.helper
    async def request(self, method, path, **kwargs):
        self.calls.append((method,path,kwargs))
        if path == "/containers/json":
            rows = [] if self.helper is None else [{"Id":"f"*64,"Names":[self.helper["Name"]],"Labels":self.helper["Config"]["Labels"]}]
            return httpx.Response(200,json=rows)
        if path == "/containers/create":
            config = kwargs["json"]
            self.helper={"Name":"/"+kwargs["params"]["name"],"Config":config,"HostConfig":config["HostConfig"],"State":{"Running":False}}
            return httpx.Response(201,json={"Id":"f"*64})
        if path.endswith("/start"):
            self.helper["State"]["Running"] = True
            return httpx.Response(204)
        if path.endswith("/wait"):
            self.helper["State"]["Running"] = False
            return httpx.Response(200,json={"StatusCode":self.exit_code})
        if path.endswith("/logs"):
            request = json.loads(self.helper["Config"]["Env"][0].split("=",1)[1])
            policy = NetworkPolicy.from_dict(request["policy"])
            raw=json.dumps({"state":"ready","fingerprint":policy.fingerprint,"bridge":policy.bridge,
                "ipv4":"direct_public_tcp_udp","ipv6":"denied","capabilities":"NET_ADMIN",
                "netns_inode":123,"rootless_owner_uid":2201}).encode()
            return httpx.Response(200,content=bytes([1,0,0,0])+len(raw).to_bytes(4,"big")+raw)
        if path.endswith("/stop"):
            self.helper["State"]["Running"] = False
            return httpx.Response(204)
        if method == "DELETE":
            self.helper = None
            return httpx.Response(204)
        raise AssertionError(path)


class RuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_bridge_apply_then_readback_and_exact_manifest(self):
        _,spec = fixture()
        engine = Engine(spec)
        helper = AsyncMock()
        with patch("node_agent.network_policy_runtime._helper",helper):
            manifest = await prepare_direct_network(engine,spec)
        self.assertEqual([call.args[2] for call in helper.await_args_list],["apply","readback"])
        validate_attestation(manifest,{"node_uuid":str(spec.node_uuid),"project_uuid":str(spec.project_uuid)},spec.container_name)
        self.assertFalse(any(path.endswith("/connect") for _,path,_ in engine.calls))
        engine.control_addresses = ()
        with patch("node_agent.network_policy_runtime._helper",AsyncMock()) as helper:
            with self.assertRaises(EngineFailure):
                await prepare_direct_network(engine,spec)
            helper.assert_not_awaited()

    async def test_resume_readback_only_and_fail_closed_exact_worker(self):
        _,spec = fixture()
        engine = Engine(spec,True)
        with patch("node_agent.network_policy_runtime._helper",AsyncMock(side_effect=EngineFailure("missing rule"))) as helper:
            with self.assertRaises(EngineFailure):
                await prepare_direct_network(engine,spec)
        self.assertEqual(helper.await_args.args[2],"readback")
        self.assertEqual([path for method,path,_ in engine.calls if method=="POST"],["/containers/"+"c"*64+"/stop"])
        engine.network["Containers"]["c"*64]["Name"] = "foreign"
        with patch("node_agent.network_policy_runtime._helper",AsyncMock()) as helper:
            with self.assertRaises(EngineFailure):
                await prepare_direct_network(engine,spec)
            helper.assert_not_awaited()

    async def test_helper_lifecycle_cleanup_and_verified_recovery(self):
        _,spec = fixture()
        policy = NetworkPolicy(str(spec.node_uuid),str(spec.id),"br-"+"b"*12,"172.30.0.0/24",("127.0.0.1",))
        engine = HelperEngine()
        result = await _helper(engine,policy,"apply")
        self.assertEqual(result["fingerprint"],policy.fingerprint)
        self.assertIsNone(engine.helper)
        engine.exit_code = 1
        with self.assertRaises(EngineFailure):
            await _helper(engine,policy,"readback")
        self.assertIsNone(engine.helper)
        config=helper_config(policy,engine.utility_image)
        engine.helper={"Name":"/"+helper_name(policy),"Config":config,"HostConfig":config["HostConfig"],"State":{"Running":True}}
        await recover_network_policy_helpers(engine,spec.node_uuid)
        self.assertIsNone(engine.helper)
        engine.helper={"Name":"/"+helper_name(policy),"Config":config,"HostConfig":{**config["HostConfig"],"Binds":["/:/host"]},"State":{"Running":True}}
        before=len(engine.calls)
        with self.assertRaises(EngineFailure):
            await recover_network_policy_helpers(engine,spec.node_uuid)
        self.assertTrue(all(method=="GET" for method,_,_ in engine.calls[before:]))

    def test_bounded_clean_docker_log_frames(self):
        raw = b'{"state":"ready"}'
        frame = bytes([1,0,0,0])+len(raw).to_bytes(4,"big")+raw
        self.assertEqual(_json_log(frame),{"state":"ready"})
        for value in (raw,bytes([2])+frame[1:],frame[:-1],b"x"*65537):
            with self.assertRaises(EngineFailure):
                _json_log(value)

    @unittest.skipUnless(hasattr(os,"geteuid") and os.geteuid()==0,"rootless initializer Linux fixture")
    def test_private_attestation_publish_idempotence_and_no_overwrite(self):
        _,spec = fixture()
        manifest={"profile":"public","node_uuid":str(spec.node_uuid),"project_uuid":str(spec.project_uuid),
            "placement_uuid":str(spec.id),"fingerprint":spec.fingerprint,"bridge":"br-"+"b"*12,
            "subnet":"172.30.0.0/24","gateway":"172.30.0.1","dns":["127.0.0.11"],"policy_sha256":"d"*64,"ready":True}
        with tempfile.TemporaryDirectory() as temporary:
            os.chmod(temporary,0o700)
            initialize_runtime(temporary,spec.container_name,manifest)
            target=Path(temporary)/"workers"/spec.container_name/"network-policy.json"
            self.assertEqual(target.stat().st_mode & 0o777,0o600)
            self.assertEqual(target.stat().st_nlink,1)
            initialize_runtime(temporary,spec.container_name,manifest)
            changed={**manifest,"policy_sha256":"e"*64}
            with self.assertRaises(ValueError):
                initialize_runtime(temporary,spec.container_name,changed)
            self.assertEqual(json.loads(target.read_bytes()),manifest)
            target.unlink()
            target.symlink_to("/etc/passwd")
            with self.assertRaises(OSError):
                initialize_runtime(temporary,spec.container_name,manifest)

if __name__ == "__main__":
    unittest.main()
