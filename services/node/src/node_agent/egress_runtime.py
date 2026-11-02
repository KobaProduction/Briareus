"""Placement-private native egress adapter; no credentials or Core route."""

import json
from typing import Protocol

from pydantic import Field, TypeAdapter

from node_protocol import Deployment

from .docker_engine import (
    DEPLOYMENT_LABEL,
    NODE_LABEL,
    SPEC_LABEL,
    EngineFailure,
    labels,
    network_name,
)
from .domain.inventory import InventoryInvalid, egress_name
from .infrastructure.container_models import (
    ContainerConfiguration,
    ContainerCreated,
    ContainerHealthcheck,
    ContainerHost,
    ContainerInspection,
    ContainerNetworking,
    ContainerSummary,
    LogConfiguration,
    NativeRecord,
    NetworkEndpoint,
)
from .infrastructure.docker_commands import NetworkConnect, NetworkCreate, NetworkIpam
from .infrastructure.docker_records import ContainerInventoryPort
from .infrastructure.docker_request import AddressingEngine
from .network_addressing import bridge_ipam, validate_network_addresses
from .runtime_profiles import EGRESS_CPU, EGRESS_MEMORY, EGRESS_PIDS, EGRESS_REQUIRED, ROLE_LABEL


class EgressEngine(AddressingEngine, ContainerInventoryPort, Protocol):
    gateway_id: str | None
    utility_image: str | None


class NetworkParticipant(NativeRecord):
    name: str = Field(default="", alias="Name")


class NetworkInspection(NativeRecord):
    identity: str = Field(default="", alias="Id")
    name: str = Field(alias="Name")
    driver: str = Field(alias="Driver")
    internal: bool = Field(alias="Internal")
    ipv6: bool | None = Field(default=None, alias="EnableIPv6")
    labels: dict[str, str] = Field(default_factory=dict, alias="Labels")
    options: dict[str, str] | None = Field(default=None, alias="Options")
    ipam: NetworkIpam = Field(default_factory=NetworkIpam, alias="IPAM")
    containers: dict[str, NetworkParticipant] = Field(default_factory=dict, alias="Containers")


def companion_name(container_name: str) -> str:
    try:
        return egress_name(container_name)
    except InventoryInvalid as exc:
        raise EngineFailure(str(exc)) from exc


async def ensure_network(
    engine: EgressEngine, spec: Deployment, name: str, *, internal: bool, role: str | None = None
) -> None:
    expected = {NODE_LABEL: str(spec.node_uuid), DEPLOYMENT_LABEL: str(spec.id)}
    if role:
        expected[ROLE_LABEL] = role
    response = await engine.request(
        "GET", "/networks", params={"filters": json.dumps({"name": [name]})}
    )
    rows = TypeAdapter(list[NetworkInspection]).validate_python(response.json())
    exact = [row for row in rows if row.name == name]
    if not exact:
        await engine.request(
            "POST",
            "/networks/create",
            accepted=(201,),
            payload=NetworkCreate(
                name=name,
                driver="bridge",
                internal=internal,
                ipv6=False,
                labels=expected,
                ipam=await bridge_ipam(engine, name),
            ),
        )
        return
    if (
        len(exact) != 1
        or exact[0].internal is not internal
        or exact[0].driver != "bridge"
        or any(exact[0].labels.get(key) != value for key, value in expected.items())
    ):
        raise EngineFailure("Conflicting placement network; refusing adoption")
    validate_network_addresses(engine, exact[0].ipam)


async def ensure_execution_network(engine: EgressEngine, spec: Deployment) -> None:
    name = network_name(spec)
    await ensure_network(engine, spec, name, internal=True)
    if engine.gateway_id is None:
        raise EngineFailure("Private Gateway unavailable")
    gateway = await engine.inspect(engine.gateway_id)
    if gateway is None:
        raise EngineFailure("Private Gateway unavailable")
    if name not in gateway.network_settings.networks:
        await engine.request(
            "POST", f"/networks/{name}/connect", payload=NetworkConnect(container=engine.gateway_id)
        )


def companion_config(spec: Deployment, image: str) -> ContainerConfiguration:
    network = network_name(spec)
    return ContainerConfiguration(
        image=image,
        user="1000:1000",
        labels={**labels(spec).model_dump(by_alias=True), ROLE_LABEL: "egress"},
        command=["/app/.venv/bin/python", "-m", "gateway_runtime.egress_proxy"],
        healthcheck=ContainerHealthcheck(
            test=[
                "CMD",
                "python",
                "-S",
                "-c",
                "import socket; s=socket.create_connection(('127.0.0.1',8080),2); "
                "s.sendall(b'GET /health/ready HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n'); "
                "line=s.makefile('rb').readline(128); s.close(); "
                "assert line.startswith((b'HTTP/1.0 ',b'HTTP/1.1 ')) "
                "and line.split(b' ',2)[1]==b'200'",
            ],
            interval=10_000_000_000,
            timeout=8_000_000_000,
            start_period=20_000_000_000,
            retries=3,
        ),
        networking=ContainerNetworking(
            endpoints={network: NetworkEndpoint(aliases=["module-egress", "web-egress"])}
        ),
        host=ContainerHost(
            network_mode=network,
            memory=EGRESS_MEMORY,
            memory_swap=EGRESS_MEMORY,
            nano_cpus=EGRESS_CPU * 1_000_000,
            pids=EGRESS_PIDS,
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=8388608"},  # noqa: S108 -- isolated container tmpfs mount target
            log=LogConfiguration(options={"max-size": "2m", "max-file": "1"}),
        ),
    )


async def matching_helpers(
    engine: EgressEngine, spec: Deployment, name: str
) -> list[ContainerSummary]:
    rows = await engine.containers(spec.node_uuid)
    return [row for row in rows if "/" + name in row.names]


async def existing_egress(
    engine: EgressEngine, spec: Deployment, name: str, desired: ContainerConfiguration
) -> str | None:
    exact = await matching_helpers(engine, spec, name)
    if not exact:
        return None
    expected = desired.labels
    if len(exact) != 1 or any(exact[0].labels.get(key) != value for key, value in expected.items()):
        raise EngineFailure("Conflicting placement egress; refusing adoption")
    helper = exact[0].identity
    current = await engine.inspect(helper)
    if (
        current is None
        or current.name != "/" + name
        or any(current.config.labels.get(key) != value for key, value in expected.items())
    ):
        raise EngineFailure("Refusing foreign placement egress replacement")
    health = (
        desired.healthcheck.model_dump(by_alias=True, exclude_none=True)
        if desired.healthcheck
        else None
    )
    actual_health = (
        current.config.healthcheck.model_dump(by_alias=True, exclude_unset=True)
        if current.config.healthcheck is not None
        else None
    )
    if actual_health == health:
        return helper
    # Inspect exact immutable ownership before replacing only the helper.
    await engine.request(
        "POST", f"/containers/{helper}/stop", params={"t": 3}, accepted=(204, 304, 404)
    )
    await engine.request("DELETE", f"/containers/{helper}", accepted=(204, 404))
    return None


async def ensure_egress(engine: EgressEngine, spec: Deployment) -> str:
    if not engine.utility_image:
        raise EngineFailure("Pinned egress runtime image required")
    name = companion_name(spec.container_name)
    external = network_name(spec) + "-egress"
    await ensure_network(engine, spec, external, internal=False, role="egress")
    desired = companion_config(spec, engine.utility_image)
    helper = await existing_egress(engine, spec, name, desired)
    if helper is None:
        created = await engine.request(
            "POST",
            "/containers/create",
            accepted=(201,),
            params={"name": name},
            payload=desired,
        )
        helper = ContainerCreated.model_validate(created.json()).identity
    current = await engine.inspect(helper)
    if current is None:
        raise EngineFailure("Placement egress unavailable")
    if external not in current.network_settings.networks:
        await engine.request(
            "POST", f"/networks/{external}/connect", payload=NetworkConnect(container=helper)
        )
    await engine.request("POST", f"/containers/{helper}/start", accepted=(204, 304))
    return helper


async def remove_companion(
    engine: EgressEngine, spec: Deployment, main: ContainerInspection
) -> None:
    metadata = main.config.labels
    if metadata.get(ROLE_LABEL) == "egress" or metadata.get(EGRESS_REQUIRED) != "true":
        return
    exact = await matching_helpers(engine, spec, companion_name(main.name.removeprefix("/")))
    if len(exact) > 1:
        raise EngineFailure("Ambiguous placement egress")
    if not exact:
        return
    helper = await engine.inspect(exact[0].identity)
    actual = helper.config.labels if helper else {}
    if (
        any(
            actual.get(key) != metadata.get(key)
            for key in (NODE_LABEL, DEPLOYMENT_LABEL, SPEC_LABEL)
        )
        or actual.get(ROLE_LABEL) != "egress"
    ):
        raise EngineFailure("Refusing foreign placement egress removal")
    await engine.request(
        "POST", f"/containers/{exact[0].identity}/stop", params={"t": 3}, accepted=(204, 304, 404)
    )
    await engine.request("DELETE", f"/containers/{exact[0].identity}", accepted=(204, 404))
