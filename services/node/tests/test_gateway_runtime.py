"""Gateway bootstrap/replacement never recreates unrelated workers."""
import unittest
from uuid import uuid4

import httpx

from node_agent.docker_engine import NODE_LABEL, DEPLOYMENT_LABEL, EngineFailure
from node_agent.gateway_runtime import ensure_gateway


class Engine:
    def __init__(self):
        self.allowed_registries = {"registry.example"}
        self.gateway_id = None
        self.gateway = None
        self.networks = []
        self.connected = set()
        self.actions = []
        self.fail_pull = False

    async def verify_rootless(self):
        pass

    async def pull_image(self, image):
        self.actions.append(("pull", image))
        if self.fail_pull:
            raise EngineFailure("Delivery failed")

    async def inspect(self, container):
        return {"NetworkSettings": {"Networks": {name: {} for name in self.connected}}}

    async def request(self, method, path, **kwargs):
        self.actions.append((method, path, kwargs))
        if method == "GET" and path == "/containers/json":
            value = [self.gateway] if self.gateway else []
        elif method == "GET" and path == "/networks":
            filters = __import__("json").loads(kwargs["params"]["filters"])
            value = [row for row in self.networks if row["Name"] in filters.get("name", [row["Name"]])
                     and ("label" not in filters or DEPLOYMENT_LABEL in row["Labels"])]
        elif path == "/networks/create":
            self.networks.append({**kwargs["json"], "Id": "network-base"})
            value = {"Id": "network-base"}
        elif path == "/containers/create":
            self.config = kwargs["json"]
            self.gateway = {"Id": "a"*64, "Names": ["/"+kwargs["params"]["name"]],
                "Labels": self.config["Labels"], "State": "created"}
            self.connected = {self.config["HostConfig"]["NetworkMode"]}
            value = {"Id": "a"*64}
        elif path.endswith("/start"):
            self.gateway["State"] = "running"
            value = {}
        elif path.endswith("/connect"):
            identity = path.split("/")[2]
            self.connected.add(next(row["Name"] for row in self.networks
                                    if row["Id"] == identity or row["Name"] == identity))
            value = {}
        else:
            raise AssertionError("Unexpected Docker effect: " + path)
        return httpx.Response(200, json=value)


class GatewayRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_only_provision_and_unchanged_controller_restart(self):
        node = uuid4()
        engine = Engine()
        engine.networks.append({"Id": "project-network", "Name": "project-network", "Internal": True,
            "Labels": {NODE_LABEL: str(node), DEPLOYMENT_LABEL: str(uuid4())}})
        image = "registry.example/node@sha256:" + "b"*64
        await ensure_gateway(engine, node_uuid=node, image=image, verify_key="public-fixture")
        host = engine.config["HostConfig"]
        self.assertFalse(host["Privileged"])
        self.assertEqual(host["CapDrop"], ["ALL"])
        self.assertEqual(host["Binds"], [f"/var/lib/briareus/nodes/{node}/gateway:/node-link:rw"])
        self.assertFalse({"PortBindings", "Devices", "VolumesFrom"} & host.keys())
        self.assertIn("project-network", engine.connected)
        before = list(engine.actions)
        await ensure_gateway(engine, node_uuid=node, image=image, verify_key="public-fixture")
        self.assertTrue(all(action[0] == "GET" for action in engine.actions[len(before):]))
        engine.fail_pull = True
        with self.assertRaises(EngineFailure):
            await ensure_gateway(engine, node_uuid=node, image="registry.example/node@sha256:"+"c"*64,
                                 verify_key="public-fixture")
        self.assertTrue(all(action[0] != "DELETE" and not (action[0] == "POST" and action[1].endswith("/stop"))
                            for action in engine.actions))
