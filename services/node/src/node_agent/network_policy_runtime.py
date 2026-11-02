"""Owned direct-network helper adapter; no worker starts before kernel readback."""

import asyncio
import ipaddress
import json
import re
from collections.abc import Mapping
from uuid import UUID

from pydantic import Field, TypeAdapter, ValidationError

from node_protocol import Deployment
from node_protocol.json_boundary import decode_json
from node_protocol.network_attestation import PublicNetworkAttestation

from .docker_engine import (
    DEPLOYMENT_LABEL,
    NODE_LABEL,
    DockerEngine,
    EngineFailure,
    labels,
    network_name,
)
from .egress_runtime import NetworkInspection
from .infrastructure.container_models import (
    ContainerCreated,
    ContainerExit,
    ContainerSummary,
    NativeRecord,
)
from .infrastructure.docker_commands import NetworkCreate
from .network_addressing import bridge_ipam, validate_network_addresses
from .network_policy import (
    DOCKER_VERSION,
    NetworkPolicy,
    PolicyAction,
    PolicyCommand,
    PolicyReadback,
    helper_config,
    helper_name,
    parse_policy,
)
from .workspace_runtime import helper_labels_match

ROLE = "io.briareus.role"


class EngineVersion(NativeRecord):
    version: str = Field(default="", alias="ServerVersion")
    security: list[str] = Field(default_factory=list, alias="SecurityOptions")


def _json_log(data: bytes) -> PolicyReadback:
    if len(data) > 65536:
        raise EngineFailure("Bounded policy helper log required")
    stdout = bytearray()
    while data:
        if len(data) < 8 or data[0] not in (1, 2) or data[1:4] != b"\0\0\0":
            raise EngineFailure("Malformed policy helper log frame")
        length = int.from_bytes(data[4:8], "big")
        if length > len(data) - 8 or (data[0] == 2 and length):
            raise EngineFailure("Policy helper did not return a clean result")
        stdout.extend(data[8 : 8 + length])
        data = data[8 + length :]
    try:
        return PolicyReadback.model_validate_json(stdout)
    except (ValueError, UnicodeError):
        raise EngineFailure("Policy helper result unavailable") from None


async def _cleanup(engine: DockerEngine, container: str, expected: Mapping[str, str]) -> None:
    async with asyncio.timeout(5):
        current = await engine.inspect(container)
        if current is None:
            return
        if not helper_labels_match(current.config.labels, expected):
            raise EngineFailure("Policy helper ownership changed")
        if current.state.running:
            await engine.request(
                "POST", f"/containers/{container}/stop", params={"t": 1}, accepted=(204, 304, 404)
            )
        await engine.request("DELETE", f"/containers/{container}", accepted=(204, 404))


async def _helper(
    engine: DockerEngine, policy: NetworkPolicy, operation: PolicyAction
) -> PolicyReadback:
    if engine.utility_image is None:
        raise EngineFailure("Approved immutable policy helper image required")
    config = helper_config(policy, engine.utility_image, operation)
    name = helper_name(policy, operation)
    response = await engine.request(
        "GET", "/containers/json", params={"all": "true", "filters": json.dumps({"name": [name]})}
    )
    rows = TypeAdapter(list[ContainerSummary]).validate_python(response.json())
    exact = [row for row in rows if "/" + name in row.names]
    if exact:
        if len(exact) != 1 or not helper_labels_match(exact[0].labels, config.labels):
            raise EngineFailure("Conflicting direct network helper")
        await _cleanup(engine, exact[0].identity, config.labels)
    created = await engine.request(
        "POST",
        "/containers/create",
        accepted=(201,),
        params={"name": name},
        payload=config,
    )
    container = ContainerCreated.model_validate(created.json()).identity
    try:
        async with asyncio.timeout(25):
            await engine.request("POST", f"/containers/{container}/start", accepted=(204, 304))
            response = await engine.request(
                "POST", f"/containers/{container}/wait", params={"condition": "not-running"}
            )
            result = ContainerExit.model_validate(response.json())
            if result.status != 0 or result.error:
                raise EngineFailure("Direct network policy helper refused")
            response = await engine.request(
                "GET",
                f"/containers/{container}/logs",
                params={"stdout": "true", "stderr": "true", "tail": "all"},
            )
            readback = _json_log(response.content)
            if (
                readback.fingerprint != policy.fingerprint
                or readback.bridge != policy.bridge
                or readback.netns_inode <= 0
                or readback.rootless_owner_uid <= 0
            ):
                raise EngineFailure("Direct network kernel readback differs from plan")
            return readback
    except TimeoutError:
        raise EngineFailure("Direct network helper exceeded deadline") from None
    finally:
        try:
            await _cleanup(engine, container, config.labels)
        except (EngineFailure, TimeoutError, ValidationError):
            engine.network_policy_cleanup_uncertain = True
            raise EngineFailure("Direct network helper cleanup unresolved") from None


async def bridge_worker(
    engine: DockerEngine, spec: Deployment, network: NetworkInspection, *, created: bool
) -> str | None:
    if len(network.containers) > 1:
        raise EngineFailure("Public execution network must be placement-private")
    current_worker = None
    for container, participant in network.containers.items():
        if (
            created
            or participant.name != spec.container_name
            or not re.fullmatch(r"[a-f0-9]{64}", container)
        ):
            raise EngineFailure("A new public bridge must be empty")
        worker = await engine.inspect(container)
        expected = labels(spec).model_dump(by_alias=True)
        if worker is None or any(
            worker.config.labels.get(key) != value for key, value in expected.items()
        ):
            raise EngineFailure("Foreign worker on public bridge")
        current_worker = container
    return current_worker


def bridge_policy(
    engine: DockerEngine, spec: Deployment, network: NetworkInspection
) -> NetworkPolicy:
    configs = network.ipam.configs or []
    if network.ipam.driver != "default" or len(configs) != 1:
        raise EngineFailure("A single private IPv4 execution subnet required")
    try:
        subnet = ipaddress.ip_network(configs[0].subnet, strict=True)
        if configs[0].gateway is None:
            raise ValueError("Invalid gateway")
        gateway = ipaddress.ip_address(configs[0].gateway)
        if (
            subnet.version != 4
            or gateway.version != 4
            or gateway not in subnet
            or gateway in {subnet.network_address, subnet.broadcast_address}
        ):
            raise ValueError("Invalid gateway")
        return NetworkPolicy(
            str(spec.node_uuid),
            str(spec.id),
            "br-" + network.identity[:12],
            str(subnet),
            engine.control_addresses,
        )
    except (ValueError, KeyError, TypeError):
        raise EngineFailure("Unverified public execution IPAM or control deny set") from None


async def prepare_direct_network(
    engine: DockerEngine, spec: Deployment
) -> PublicNetworkAttestation:
    if engine.network_policy_cleanup_uncertain:
        raise EngineFailure("Direct network helper cleanup unresolved")
    if not engine.utility_image:
        raise EngineFailure("Approved immutable policy helper image required")
    info = EngineVersion.model_validate((await engine.request("GET", "/info")).json())
    if info.version != DOCKER_VERSION or "name=rootless" not in info.security:
        raise EngineFailure("Accepted rootless Docker 28.3.2 required")
    name = network_name(spec) + "-public"
    expected = {
        NODE_LABEL: str(spec.node_uuid),
        DEPLOYMENT_LABEL: str(spec.id),
        ROLE: "public-execution",
    }
    response = await engine.request("GET", "/networks/" + name, accepted=(200, 404))
    created = response.status_code == 404
    if created:
        await engine.request(
            "POST",
            "/networks/create",
            accepted=(201,),
            payload=NetworkCreate(
                name=name,
                driver="bridge",
                internal=False,
                ipv6=False,
                labels=expected,
                ipam=await bridge_ipam(engine, name),
            ),
        )
        response = await engine.request("GET", "/networks/" + name)
    network = NetworkInspection.model_validate(response.json())
    validate_network_addresses(engine, network.ipam)
    if (
        network.name != name
        or not re.fullmatch(r"[a-f0-9]{64}", network.identity)
        or network.driver != "bridge"
        or network.internal is not False
        or network.ipv6 is not False
        or network.options not in (None, {})
        or not helper_labels_match(network.labels, expected)
    ):
        raise EngineFailure("Refusing foreign or unverified public execution bridge")
    current_worker = await bridge_worker(engine, spec, network, created=created)
    policy = bridge_policy(engine, spec, network)
    try:
        if current_worker is None:
            await _helper(engine, policy, "apply")
        await _helper(engine, policy, "readback")
    except EngineFailure:
        if current_worker is not None:
            await engine.request(
                "POST",
                f"/containers/{current_worker}/stop",
                params={"t": 1},
                accepted=(204, 304, 404),
            )
        raise
    config = (network.ipam.configs or [])[0]
    return PublicNetworkAttestation(
        profile="public",
        ready=True,
        node_uuid=spec.node_uuid,
        project_uuid=spec.project_uuid,
        placement_uuid=spec.id,
        fingerprint=spec.fingerprint,
        bridge=policy.bridge,
        subnet=policy.ipv4_subnet,
        gateway=str(ipaddress.ip_address(config.gateway or "")),
        dns=["127.0.0.11"],
        policy_sha256=policy.fingerprint,
    )


async def recover_network_policy_helpers(engine: DockerEngine, node_uuid: UUID) -> None:
    response = await engine.request(
        "GET",
        "/containers/json",
        params={
            "all": "true",
            "filters": json.dumps(
                {"label": [NODE_LABEL + "=" + str(node_uuid), ROLE + "=network-policy-helper"]}
            ),
        },
    )
    for row in TypeAdapter(list[ContainerSummary]).validate_python(response.json()):
        current = await engine.inspect(row.identity)
        try:
            if current is None:
                raise ValueError("Missing helper")
            actual = current.config
            entries = [
                value.split("=", 1)[1]
                for value in actual.environment
                if value.startswith("BRIAREUS_NETWORK_POLICY_REQUEST=")
            ]
            if len(entries) != 1:
                raise ValueError("Missing fixed request")
            request = decode_json(entries[0], PolicyCommand)
            policy = parse_policy(request.policy)
            expected_config = helper_config(policy, actual.image, request.action)
            expected = expected_config.labels
            host = current.host
            if (
                not host.matches_isolation(expected_config.host)
                or policy.node_uuid != str(node_uuid)
                or actual.command != expected_config.command
                or actual.user != "0:0"
                or not helper_labels_match(actual.labels, expected)
                or "/" + helper_name(policy, request.action) not in row.names
                or not helper_labels_match(row.labels, expected)
            ):
                raise ValueError("Unverified helper")
        except (ValueError, KeyError, TypeError):
            raise EngineFailure("Refusing to reap an unverified direct network helper") from None
        await _cleanup(engine, row.identity, expected)
    engine.network_policy_cleanup_uncertain = False
