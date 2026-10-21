"""Owned direct-network bootstrap; no worker starts before kernel readback."""
from __future__ import annotations

import asyncio
import ipaddress
import json
import re

from .docker_engine import NODE_LABEL, DEPLOYMENT_LABEL, EngineFailure, labels, network_name
from .network_policy import DOCKER_VERSION, NetworkPolicy, helper_config, helper_name
from .workspace_runtime import helper_labels_match

ROLE = "io.briareus.role"


def _json_log(data):
    if not isinstance(data, bytes) or len(data) > 65536:
        raise EngineFailure("Bounded policy helper log required")
    stdout = bytearray()
    # Docker's non-TTY logs endpoint multiplexes stdout/stderr in 8-byte frames.
    while data:
        if len(data) < 8 or data[0] not in (1, 2) or data[1:4] != b"\0\0\0":
            raise EngineFailure("Malformed policy helper log frame")
        length = int.from_bytes(data[4:8], "big")
        if length > len(data) - 8 or data[0] == 2 and length:
            raise EngineFailure("Policy helper did not return a clean result")
        stdout.extend(data[8:8+length])
        data = data[8+length:]
    try:
        result = json.loads(stdout)
    except (ValueError, UnicodeError):
        raise EngineFailure("Policy helper result unavailable") from None
    if not isinstance(result, dict):
        raise EngineFailure("Policy helper object required")
    return result


async def _cleanup(engine, container, expected):
    async with asyncio.timeout(5):
        current = await engine.inspect(container)
        if not current:
            return
        if not helper_labels_match(current.get("Config", {}).get("Labels"), expected):
            raise EngineFailure("Policy helper ownership changed")
        if current.get("State", {}).get("Running"):
            await engine.request("POST", f"/containers/{container}/stop", params={"t":1}, accepted=(204,304,404))
        await engine.request("DELETE", f"/containers/{container}", accepted=(204,404))


async def _helper(engine, policy, operation):
    config = helper_config(policy, engine.utility_image, operation)
    name = helper_name(policy, operation)
    rows = (await engine.request("GET", "/containers/json", params={"all":"true",
        "filters":json.dumps({"name":[name]})})).json()
    exact = [row for row in rows if "/"+name in row.get("Names", [])]
    if exact:
        # Reap a previous owned one-shot rather than trusting stale stdout.
        if len(exact) != 1 or not helper_labels_match(exact[0].get("Labels"), config["Labels"]):
            raise EngineFailure("Conflicting direct network helper")
        await _cleanup(engine, exact[0]["Id"], config["Labels"])
    created = await engine.request("POST", "/containers/create", accepted=(201,),
        params={"name":name}, json=config)
    container = created.json()["Id"]
    try:
        async with asyncio.timeout(25):
            await engine.request("POST", f"/containers/{container}/start", accepted=(204,304))
            result = (await engine.request("POST", f"/containers/{container}/wait",
                params={"condition":"not-running"})).json()
            if type(result.get("StatusCode")) is not int or result["StatusCode"] != 0 or result.get("Error"):
                raise EngineFailure("Direct network policy helper refused")
            response = await engine.request("GET", f"/containers/{container}/logs",
                params={"stdout":"true", "stderr":"true", "tail":"all"})
            result = _json_log(response.content)
            if (result.get("state") != "ready" or result.get("fingerprint") != policy.fingerprint
                or result.get("bridge") != policy.bridge or result.get("ipv4") != "direct_public_tcp_udp"
                or result.get("ipv6") != "denied" or result.get("capabilities") != "NET_ADMIN"
                or type(result.get("netns_inode")) is not int or result["netns_inode"] <= 0
                or type(result.get("rootless_owner_uid")) is not int or result["rootless_owner_uid"] <= 0):
                raise EngineFailure("Direct network kernel readback differs from plan")
            return result
    except TimeoutError:
        raise EngineFailure("Direct network helper exceeded deadline") from None
    finally:
        try:
            await _cleanup(engine, container, config["Labels"])
        except (EngineFailure, TimeoutError):
            engine.network_policy_cleanup_uncertain = True
            raise EngineFailure("Direct network helper cleanup unresolved") from None


async def prepare_direct_network(engine, spec):
    if getattr(engine, "network_policy_cleanup_uncertain", False):
        raise EngineFailure("Direct network helper cleanup unresolved")
    if not engine.utility_image:
        raise EngineFailure("Approved immutable policy helper image required")
    info = (await engine.request("GET", "/info")).json()
    if info.get("ServerVersion") != DOCKER_VERSION or "name=rootless" not in info.get("SecurityOptions", []):
        raise EngineFailure("Accepted rootless Docker 28.3.2 required")
    name = network_name(spec) + "-public"
    expected = {NODE_LABEL:str(spec.node_uuid), DEPLOYMENT_LABEL:str(spec.id), ROLE:"public-execution"}
    response = await engine.request("GET", "/networks/" + name, accepted=(200,404))
    created = response.status_code == 404
    if created:
        from .network_addressing import bridge_ipam
        await engine.request("POST", "/networks/create", accepted=(201,), json={
            "Name":name, "Driver":"bridge", "Internal":False, "EnableIPv6":False, "Labels":expected,
            "IPAM":await bridge_ipam(engine,name)})
        response = await engine.request("GET", "/networks/" + name)
    network = response.json()
    from .network_addressing import validate_network_addresses
    validate_network_addresses(engine,network)
    identifier = network.get("Id", "")
    if (network.get("Name") != name or not re.fullmatch(r"[a-f0-9]{64}", identifier)
        or network.get("Driver") != "bridge" or network.get("Internal") is not False
        or network.get("EnableIPv6") is not False or network.get("Options") not in (None,{})
        or not helper_labels_match(network.get("Labels"), expected)):
        raise EngineFailure("Refusing foreign or unverified public execution bridge")
    participants = network.get("Containers", {})
    if not isinstance(participants, dict) or len(participants) > 1:
        raise EngineFailure("Public execution network must be placement-private")
    current_worker = None
    for container, participant in participants.items():
        if (created or not isinstance(participant, dict) or participant.get("Name") != spec.container_name
            or not re.fullmatch(r"[a-f0-9]{64}", container)):
            raise EngineFailure("A new public bridge must be empty")
        worker = await engine.inspect(container)
        if not worker or any(worker.get("Config",{}).get("Labels",{}).get(key) != value
                             for key,value in labels(spec).items()):
            raise EngineFailure("Foreign worker on public bridge")
        current_worker = container
    ipam = network.get("IPAM", {})
    configs = ipam.get("Config", [])
    if ipam.get("Driver") != "default" or len(configs) != 1:
        raise EngineFailure("A single private IPv4 execution subnet required")
    try:
        subnet = ipaddress.ip_network(configs[0]["Subnet"], strict=True)
        gateway = ipaddress.ip_address(configs[0]["Gateway"])
        if (subnet.version != 4 or gateway.version != 4 or gateway not in subnet
            or gateway in {subnet.network_address, subnet.broadcast_address}):
            raise ValueError("Invalid gateway")
        addresses = tuple(getattr(engine, "control_addresses", ()))
        policy = NetworkPolicy(str(spec.node_uuid),str(spec.id),"br-"+identifier[:12],str(subnet),addresses)
    except (ValueError,KeyError,TypeError):
        raise EngineFailure("Unverified public execution IPAM or control deny set") from None
    try:
        if current_worker is None:
            await _helper(engine, policy, "apply")
        await _helper(engine, policy, "readback")
    except EngineFailure:
        # A resumed worker with missing/tampered rules must not keep its
        # unverified route. Stop only that exact owned target, preserving data.
        if current_worker is not None:
            await engine.request("POST", f"/containers/{current_worker}/stop", params={"t":1}, accepted=(204,304,404))
        raise
    return {"profile":"public", "node_uuid":str(spec.node_uuid), "project_uuid":str(spec.project_uuid),
        "placement_uuid":str(spec.id), "fingerprint":spec.fingerprint, "bridge":policy.bridge,
        "subnet":str(subnet), "gateway":str(gateway), "dns":["127.0.0.11"],
        "policy_sha256":policy.fingerprint, "ready":True}


async def recover_network_policy_helpers(engine, node_uuid):
    rows = (await engine.request("GET", "/containers/json", params={"all":"true", "filters":json.dumps({
        "label":[NODE_LABEL+"="+str(node_uuid), ROLE+"=network-policy-helper"]})})).json()
    for row in rows:
        current = await engine.inspect(row["Id"])
        actual = current.get("Config", {}) if current else {}
        entries = [value.split("=",1)[1] for value in actual.get("Env", [])
                   if value.startswith("BRIAREUS_NETWORK_POLICY_REQUEST=")]
        try:
            if len(entries) != 1:
                raise ValueError("Missing fixed request")
            request = json.loads(entries[0])
            policy = NetworkPolicy.from_dict(request["policy"])
            operation = request["action"]
            expected_config = helper_config(policy, actual["Image"], operation)
            expected = expected_config["Labels"]
            host = current.get("HostConfig", {})
            fixed = expected_config["HostConfig"]
            if (set(request) != {"action", "policy"}
                or any(host.get(key) != fixed[key] for key in ("NetworkMode", "ReadonlyRootfs", "Privileged", "CapDrop", "CapAdd", "SecurityOpt"))
                or any(host.get(key) for key in ("Binds", "Mounts", "Devices", "DeviceRequests", "VolumesFrom"))
                or policy.node_uuid != str(node_uuid) or actual.get("Cmd") != expected_config["Cmd"]
                or actual.get("User") != "0:0" or not helper_labels_match(actual.get("Labels"), expected)
                or "/"+helper_name(policy,operation) not in row.get("Names", [])
                or not helper_labels_match(row.get("Labels"), expected)):
                raise ValueError("Unverified helper")
        except (ValueError,KeyError,TypeError):
            raise EngineFailure("Refusing to reap an unverified direct network helper") from None
        await _cleanup(engine, row["Id"], expected)
    engine.network_policy_cleanup_uncertain = False
