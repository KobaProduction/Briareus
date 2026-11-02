"""Native dedicated Gateway adapter, preserving all independently running workers."""

import hashlib
import json
import re
from uuid import UUID

from pydantic import TypeAdapter

from node_protocol.control import canonical
from node_protocol.runtime import GATEWAY_LIMITS

from .application.gateway_stage import EnsureGateway
from .docker_engine import DEPLOYMENT_LABEL, NODE_LABEL, DockerEngine, EngineFailure
from .domain.gateway_stage import GatewayCandidate
from .domain.worker_stage import WorkerStageFailure
from .egress_runtime import NetworkInspection
from .infrastructure.container_models import (
    ContainerConfiguration,
    ContainerCreated,
    ContainerHost,
    ContainerSummary,
    LogConfiguration,
    RestartPolicy,
)
from .infrastructure.docker_commands import NetworkConnect, NetworkCreate
from .infrastructure.runtime_bindings import _ContainerStart
from .network_addressing import bridge_ipam

ROLE = "io.briareus.role"
CONFIG = "io.briareus.gateway-config"


class DockerGateway(_ContainerStart):
    def __init__(
        self,
        engine: DockerEngine,
        node_uuid: UUID,
        image: str,
        verify_key: str,
        core_verify_key: str | None = None,
    ) -> None:
        self.engine, self.node_uuid, self.image, self.verify_key = (
            engine,
            node_uuid,
            image,
            verify_key,
        )
        self.core_verify_key = core_verify_key
        self.name = "briareus-node-gateway-" + node_uuid.hex
        self.network = self.name + "-ingress"
        self._fingerprint = hashlib.sha256(
            canonical(
                {"node_uuid": str(node_uuid), "image": image, "gateway_verify_key": verify_key}
            )
        ).hexdigest()

        if core_verify_key is not None:
            self._fingerprint = hashlib.sha256(
                canonical(
                    {
                        "gateway_fingerprint": self._fingerprint,
                        "core_verify_key": core_verify_key,
                    }
                )
            ).hexdigest()

    def fingerprint(self) -> str:
        return self._fingerprint

    async def verify(self) -> None:
        if (
            not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", self.image)
            or self.image.split("/", 1)[0] not in self.engine.allowed_registries
        ):
            raise EngineFailure("Approved immutable Node Gateway image required")
        await self.engine.verify_rootless()
        self.engine.utility_image = self.image

    async def candidates(self) -> tuple[GatewayCandidate, ...]:
        response = await self.engine.request(
            "GET",
            "/containers/json",
            params={"all": "true", "filters": json.dumps({"name": [self.name]})},
        )
        rows = TypeAdapter(list[ContainerSummary]).validate_python(response.json())
        return tuple(
            GatewayCandidate(
                row.identity,
                row.labels.get(NODE_LABEL) == str(self.node_uuid)
                and row.labels.get(ROLE) == "gateway",
                row.labels.get(CONFIG, ""),
                row.state == "running",
            )
            for row in rows
            if "/" + self.name in row.names
        )

    async def pull(self) -> None:
        await self.engine.pull_image(self.image)

    async def ensure_ingress(self) -> None:
        response = await self.engine.request(
            "GET", "/networks", params={"filters": json.dumps({"name": [self.network]})}
        )
        rows = TypeAdapter(list[NetworkInspection]).validate_python(response.json())
        exact = [row for row in rows if row.name == self.network]
        if not exact:
            await self.engine.request(
                "POST",
                "/networks/create",
                accepted=(201,),
                payload=NetworkCreate(
                    name=self.network,
                    driver="bridge",
                    internal=True,
                    ipv6=False,
                    labels={NODE_LABEL: str(self.node_uuid), ROLE: "gateway"},
                    ipam=await bridge_ipam(self.engine, self.network),
                ),
            )
        elif (
            len(exact) != 1
            or exact[0].internal is not True
            or exact[0].labels.get(NODE_LABEL) != str(self.node_uuid)
            or exact[0].labels.get(ROLE) != "gateway"
        ):
            raise EngineFailure("Conflicting private Gateway network")

    async def remove(self, container: str) -> None:
        await self.engine.request(
            "POST", f"/containers/{container}/stop", params={"t": 10}, accepted=(204, 304)
        )
        await self.engine.request("DELETE", f"/containers/{container}", accepted=(204,))

    async def create(self) -> str:
        config = ContainerConfiguration(
            image=self.image,
            user="0:0",
            labels={NODE_LABEL: str(self.node_uuid), ROLE: "gateway", CONFIG: self._fingerprint},
            command=["/app/.venv/bin/python", "-m", "node_agent.gateway_server"],
            environment=[
                "BRIAREUS_NODE_UUID=" + str(self.node_uuid),
                "BRIAREUS_GATEWAY_VERIFY_KEY=" + self.verify_key,
                *(
                    ["BRIAREUS_CORE_VERIFY_KEY=" + self.core_verify_key]
                    if self.core_verify_key
                    else []
                ),
            ],
            host=ContainerHost(
                network_mode=self.network,
                restart=RestartPolicy(name="unless-stopped"),
                memory=GATEWAY_LIMITS.memory_bytes,
                memory_swap=GATEWAY_LIMITS.memory_bytes,
                nano_cpus=GATEWAY_LIMITS.cpu_millis * 1_000_000,
                pids=GATEWAY_LIMITS.pids,
                binds=[f"/var/lib/briareus/nodes/{self.node_uuid}/gateway:/node-link:rw"],
                tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=16777216"},  # noqa: S108 -- isolated container tmpfs mount target
                log=LogConfiguration(options={"max-size": "5m", "max-file": "2"}),
            ),
        )
        response = await self.engine.request(
            "POST",
            "/containers/create",
            accepted=(201,),
            params={"name": self.name},
            payload=config,
        )
        return ContainerCreated.model_validate(response.json()).identity

    async def reconnect(self, container: str) -> None:
        self.engine.gateway_id = container
        response = await self.engine.request(
            "GET",
            "/networks",
            params={
                "filters": json.dumps(
                    {"label": [f"{NODE_LABEL}={self.node_uuid}", DEPLOYMENT_LABEL]}
                )
            },
        )
        rows = TypeAdapter(list[NetworkInspection]).validate_python(response.json())
        current = await self.engine.inspect(container)
        attached = current.network_settings.networks if current else {}
        for network in rows:
            if network.labels.get(ROLE) in {"egress", "public-execution"}:
                require_public_network(network, self.node_uuid)
                continue
            if network.internal is not True or network.labels.get(NODE_LABEL) != str(
                self.node_uuid
            ):
                raise EngineFailure("Unverified execution network")
            if network.name not in attached:
                await self.engine.request(
                    "POST",
                    f"/networks/{network.identity}/connect",
                    payload=NetworkConnect(container=container),
                )


def require_public_network(network: NetworkInspection, node_uuid: UUID) -> None:
    try:
        placement = UUID(network.labels[DEPLOYMENT_LABEL])
        suffix = "-egress" if network.labels.get(ROLE) == "egress" else "-public"
        expected = f"briareus-{node_uuid.hex}-{placement.hex}" + suffix
        valid = (
            placement.version == 4
            and network.name == expected
            and network.internal is False
            and network.driver == "bridge"
            and network.labels.get(NODE_LABEL) == str(node_uuid)
        )
    except (ValueError, KeyError, TypeError):
        valid = False
    if not valid:
        raise EngineFailure("Unverified public execution network")


async def ensure_gateway(
    engine: DockerEngine,
    *,
    node_uuid: UUID,
    image: str,
    verify_key: str,
    core_verify_key: str | None = None,
) -> str:
    try:
        return await EnsureGateway(
            DockerGateway(engine, node_uuid, image, verify_key, core_verify_key)
        ).execute()
    except EngineFailure:
        raise
    except WorkerStageFailure as exc:
        raise EngineFailure(str(exc)) from exc
