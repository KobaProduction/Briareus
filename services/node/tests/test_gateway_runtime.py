"""Gateway bootstrap/replacement never recreates unrelated workers."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

import httpx
from node_agent.docker_engine import DEPLOYMENT_LABEL, NODE_LABEL, DockerEngine, EngineFailure
from node_agent.egress_runtime import NetworkInspection
from node_agent.gateway_runtime import ensure_gateway
from node_agent.infrastructure.container_models import ContainerConfiguration, ContainerSummary
from node_agent.infrastructure.docker_commands import NetworkCreate
from pydantic import BaseModel
from test_native_replacement_repair import NativeDaemon
from test_reconciliation import fixture

from node_protocol import Deployment


class Filters(BaseModel):
    name: list[str] | None = None
    label: list[str] | None = None


class GatewayDaemon(NativeDaemon):
    def __init__(self, spec: Deployment) -> None:
        super().__init__(spec)
        self.gateway: ContainerSummary | None = None
        self.config: ContainerConfiguration | None = None
        self.networks: list[NetworkInspection] = []
        self.connected: set[str] = set()
        self.fail_pull = False

    def respond(self, request: httpx.Request) -> httpx.Response:
        method, path = request.method, request.url.path.removeprefix("/v1.51")
        self.seen.append((method, path))
        if method == "GET" and path == "/containers/json":
            return httpx.Response(
                200, json=[self.gateway.model_dump(by_alias=True)] if self.gateway else []
            )
        if method == "GET" and path == "/networks":
            filters = Filters.model_validate_json(request.url.params.get("filters", "{}"))
            rows = [
                row
                for row in self.networks
                if (filters.name is None or row.name in filters.name)
                and (filters.label is None or DEPLOYMENT_LABEL in row.labels)
            ]
            return httpx.Response(200, json=[row.model_dump(by_alias=True) for row in rows])
        if path == "/networks/create":
            network = NetworkCreate.model_validate_json(request.content)
            self.networks.append(
                NetworkInspection.model_validate(
                    {**network.model_dump(by_alias=True), "Id": "network-base"}
                )
            )
            return httpx.Response(201, json={"Id": "network-base"})
        if path == "/containers/create":
            self.config = ContainerConfiguration.model_validate_json(request.content)
            self.gateway = ContainerSummary(
                identity="a" * 64,
                names=["/" + request.url.params["name"]],
                labels=self.config.labels,
                state="created",
            )
            self.connected = {self.config.host.network_mode}
            return httpx.Response(201, json={"Id": "a" * 64})
        if method == "GET" and path == "/containers/" + "a" * 64 + "/json":
            return httpx.Response(
                200,
                json={
                    "Id": "a" * 64,
                    "NetworkSettings": {"Networks": {name: {} for name in self.connected}},
                },
            )
        if path.endswith("/start"):
            assert self.gateway is not None
            self.gateway.state = "running"
            return httpx.Response(204)
        if path.endswith("/connect"):
            identity = path.split("/")[2]
            self.connected.add(
                next(
                    row.name
                    for row in self.networks
                    if row.identity == identity or row.name == identity
                )
            )
            return httpx.Response(200, json={})
        if path == "/images/create":
            return httpx.Response(500 if self.fail_pull else 200, content=b"{}\n")
        raise AssertionError("Unexpected Docker effect: " + path)


class GatewayRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_gateway_only_provision_and_unchanged_controller_restart(self) -> None:
        record, spec = fixture()
        node = record.id
        daemon = GatewayDaemon(spec)
        daemon.networks.append(
            NetworkInspection(
                identity="project-network",
                name="project-network",
                driver="bridge",
                internal=True,
                labels={NODE_LABEL: str(node), DEPLOYMENT_LABEL: str(uuid4())},
            )
        )
        async with daemon.engine() as engine:
            engine.control_addresses = ("172.25.80.1",)
            with patch.object(engine, "verify_rootless", new_callable=AsyncMock):
                await self.exercise_gateway(daemon, engine, node)

    async def exercise_gateway(
        self, daemon: GatewayDaemon, engine: DockerEngine, node: UUID
    ) -> None:
        image = "registry.example/node@sha256:" + "b" * 64
        await ensure_gateway(engine, node_uuid=node, image=image, verify_key="public-fixture")
        assert daemon.config is not None
        host = daemon.config.host
        self.assertFalse(host.privileged)
        self.assertEqual(host.cap_drop, ["ALL"])
        self.assertEqual(host.binds, [f"/var/lib/briareus/nodes/{node}/gateway:/node-link:rw"])
        self.assertFalse(
            {"PortBindings", "Devices", "VolumesFrom"} & host.model_dump(by_alias=True).keys()
        )
        self.assertIn("project-network", daemon.connected)
        before = list(daemon.seen)
        await ensure_gateway(engine, node_uuid=node, image=image, verify_key="public-fixture")
        self.assertTrue(all(action[0] == "GET" for action in daemon.seen[len(before) :]))
        daemon.fail_pull = True
        with self.assertRaises(EngineFailure):
            await ensure_gateway(
                engine,
                node_uuid=node,
                image="registry.example/node@sha256:" + "c" * 64,
                verify_key="public-fixture",
            )
        self.assertTrue(
            all(
                action[0] != "DELETE" and not (action[0] == "POST" and action[1].endswith("/stop"))
                for action in daemon.seen
            )
        )
