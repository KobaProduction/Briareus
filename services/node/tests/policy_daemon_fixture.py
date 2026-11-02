"""Native HTTP fixtures for policy readback and one-shot helper ownership."""

import httpx
from node_agent.docker_engine import DEPLOYMENT_LABEL, NODE_LABEL, labels, network_name
from node_agent.egress_runtime import NetworkInspection
from node_agent.infrastructure.container_models import (
    ContainerConfiguration,
    ContainerInspection,
    InspectedState,
)
from node_agent.network_policy import PolicyCommand, PolicyReadback, parse_policy
from test_native_replacement_repair import NativeDaemon

from node_protocol import Deployment

IMAGE = "registry.example/node@sha256:" + "a" * 64
HELPER_ID = "f" * 64


def helper_inspection(config: ContainerConfiguration, name: str) -> ContainerInspection:
    return ContainerInspection.model_validate(
        {
            "Id": HELPER_ID,
            "Name": "/" + name,
            "Config": config.model_dump(by_alias=True, exclude_none=True),
            "HostConfig": config.host.model_dump(by_alias=True, exclude_none=True),
            "State": {"Running": True},
        }
    )


class PolicyNetworkDaemon(NativeDaemon):
    def __init__(self, spec: Deployment, *, running: bool = False) -> None:
        super().__init__(spec)
        self.network = NetworkInspection.model_validate(
            {
                "Name": network_name(spec) + "-public",
                "Id": "b" * 64,
                "Driver": "bridge",
                "Internal": False,
                "EnableIPv6": False,
                "Options": {},
                "Labels": {
                    NODE_LABEL: str(spec.node_uuid),
                    DEPLOYMENT_LABEL: str(spec.id),
                    "io.briareus.role": "public-execution",
                },
                "IPAM": {
                    "Driver": "default",
                    "Config": [{"Subnet": "172.30.0.0/24", "Gateway": "172.30.0.1"}],
                },
                "Containers": {"c" * 64: {"Name": spec.container_name}} if running else {},
            }
        )

    def respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.51")
        self.seen.append((request.method, path))
        if path == "/info":
            return httpx.Response(
                200, json={"ServerVersion": "28.3.2", "SecurityOptions": ["name=rootless"]}
            )
        if path.startswith("/networks/"):
            return httpx.Response(200, content=self.network.model_dump_json(by_alias=True))
        if path == "/containers/" + "c" * 64 + "/json":
            return httpx.Response(
                200,
                json={
                    "Id": "c" * 64,
                    "Config": {"Labels": labels(self.spec).model_dump(by_alias=True)},
                },
            )
        if path.endswith("/stop"):
            return httpx.Response(204)
        raise AssertionError(path)


class PolicyHelperDaemon(NativeDaemon):
    def __init__(self, spec: Deployment) -> None:
        super().__init__(spec)
        self.helper: ContainerInspection | None = None
        self.exit_code = 0

    def respond(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path.removeprefix("/v1.51")
        self.seen.append((request.method, path))
        if path == "/containers/json":
            rows = (
                []
                if self.helper is None
                else [
                    {
                        "Id": HELPER_ID,
                        "Names": [self.helper.name],
                        "Labels": self.helper.config.labels,
                    }
                ]
            )
            return httpx.Response(200, json=rows)
        if path == "/containers/create":
            config = ContainerConfiguration.model_validate_json(request.content)
            self.helper = helper_inspection(config, request.url.params["name"])
            self.helper.state = InspectedState(running=False)
            return httpx.Response(201, json={"Id": HELPER_ID})
        if path == f"/containers/{HELPER_ID}/json":
            return (
                httpx.Response(200, content=self.helper.model_dump_json(by_alias=True))
                if self.helper
                else httpx.Response(404, json={})
            )
        assert self.helper is not None
        if path.endswith("/start"):
            self.helper.state = InspectedState(running=True)
            return httpx.Response(204)
        if path.endswith("/wait"):
            self.helper.state = InspectedState(running=False)
            return httpx.Response(200, json={"StatusCode": self.exit_code})
        if path.endswith("/logs"):
            command = PolicyCommand.model_validate_json(
                self.helper.config.environment[0].split("=", 1)[1]
            )
            policy = parse_policy(command.policy)
            raw = (
                PolicyReadback(
                    fingerprint=policy.fingerprint,
                    bridge=policy.bridge,
                    netns_inode=123,
                    rootless_owner_uid=2201,
                )
                .model_dump_json()
                .encode()
            )
            return httpx.Response(
                200, content=bytes([1, 0, 0, 0]) + len(raw).to_bytes(4, "big") + raw
            )
        if path.endswith("/stop"):
            self.helper.state = InspectedState(running=False)
            return httpx.Response(204)
        if request.method == "DELETE":
            self.helper = None
            return httpx.Response(204)
        raise AssertionError(path)
