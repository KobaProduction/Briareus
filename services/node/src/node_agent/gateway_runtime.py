"""Provision only the dedicated rootless Gateway, preserving MCP workers."""
import hashlib
import json
import re

from node_protocol.control import canonical
from node_protocol.runtime import GATEWAY_LIMITS
from .docker_engine import DEPLOYMENT_LABEL, NODE_LABEL, EngineFailure

ROLE = "io.briareus.role"
CONFIG = "io.briareus.gateway-config"


async def ensure_gateway(engine, *, node_uuid, image, verify_key):
    if (not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", image)
        or image.split("/", 1)[0] not in engine.allowed_registries):
        raise EngineFailure("Approved immutable Node Gateway image required")
    await engine.verify_rootless()
    engine.utility_image = image
    name = "briareus-node-gateway-" + node_uuid.hex
    network = name + "-ingress"
    fingerprint = hashlib.sha256(canonical({"node_uuid": str(node_uuid), "image": image,
                                           "gateway_verify_key": verify_key})).hexdigest()
    labels = {NODE_LABEL: str(node_uuid), ROLE: "gateway", CONFIG: fingerprint}
    response = await engine.request("GET", "/containers/json", params={"all": "true",
        "filters": json.dumps({"name": [name]})})
    exact = [row for row in response.json() if "/" + name in row.get("Names", [])]
    if len(exact) > 1 or any(row.get("Labels", {}).get(NODE_LABEL) != str(node_uuid)
                             or row.get("Labels", {}).get(ROLE) != "gateway" for row in exact):
        raise EngineFailure("Refusing to adopt a foreign Gateway container")
    if exact and exact[0].get("Labels", {}).get(CONFIG) == fingerprint:
        gateway_id = exact[0]["Id"]
        if exact[0].get("State") != "running":
            await engine.request("POST", f"/containers/{gateway_id}/start", accepted=(204, 304))
    else:
        # Image delivery failure leaves the existing Gateway running.
        await engine.pull_image(image)
        networks = (await engine.request("GET", "/networks", params={
            "filters": json.dumps({"name": [network]})})).json()
        existing = [row for row in networks if row.get("Name") == network]
        if not existing:
            from .network_addressing import bridge_ipam
            await engine.request("POST", "/networks/create", accepted=(201,), json={"Name": network,
                "Driver": "bridge", "Internal": True, "EnableIPv6": False, "Labels": {
                    NODE_LABEL: str(node_uuid), ROLE: "gateway"}, "IPAM":await bridge_ipam(engine,network)})
        elif (len(existing) != 1 or existing[0].get("Internal") is not True
              or existing[0].get("Labels", {}).get(NODE_LABEL) != str(node_uuid)
              or existing[0].get("Labels", {}).get(ROLE) != "gateway"):
            raise EngineFailure("Conflicting private Gateway network")
        if exact:
            old = exact[0]["Id"]
            await engine.request("POST", f"/containers/{old}/stop", params={"t": 10}, accepted=(204, 304))
            await engine.request("DELETE", f"/containers/{old}", accepted=(204,))
        created = await engine.request("POST", "/containers/create", accepted=(201,), params={"name": name},
            json={"Image": image, "User": "0:0", "Labels": labels,
                # UID 0 here maps to the dedicated NON-ROOT host runtime UID;
                # this trusted relay needs to own its private host Unix socket.
                "Cmd": ["/app/.venv/bin/python", "-m", "node_agent.gateway_server"],
                "Env": ["BRIAREUS_NODE_UUID=" + str(node_uuid), "BRIAREUS_GATEWAY_VERIFY_KEY=" + verify_key],
                "HostConfig": {"NetworkMode": network, "CapDrop": ["ALL"],
                    "SecurityOpt": ["no-new-privileges:true"], "ReadonlyRootfs": True,
                    "Privileged": False, "PublishAllPorts": False, "RestartPolicy": {"Name": "unless-stopped"},
                    "Memory": GATEWAY_LIMITS.memory_bytes, "MemorySwap": GATEWAY_LIMITS.memory_bytes,
                    "NanoCpus": GATEWAY_LIMITS.cpu_millis * 1000000, "PidsLimit": GATEWAY_LIMITS.pids,
                    "Binds": [f"/var/lib/briareus/nodes/{node_uuid}/gateway:/node-link:rw"],
                    "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=16777216"},
                    "LogConfig": {"Type": "json-file", "Config": {"max-size": "5m", "max-file": "2"}}}})
        gateway_id = created.json()["Id"]
        await engine.request("POST", f"/containers/{gateway_id}/start", accepted=(204,))
    engine.gateway_id = gateway_id
    # Gateway replacement reconnects all owned placement networks, with no
    # worker stop/start. Existing internal networks are never deleted here.
    networks = (await engine.request("GET", "/networks", params={"filters": json.dumps({
        "label": [f"{NODE_LABEL}={node_uuid}", DEPLOYMENT_LABEL]})})).json()
    current = await engine.inspect(gateway_id)
    attached = current.get("NetworkSettings", {}).get("Networks", {}) if current else {}
    for network in networks:
        role = network.get("Labels",{}).get(ROLE)
        if role in {"egress","public-execution"}:
            # Only workers/helpers use internet-capable bridges. The Gateway
            # remains exclusively on its private ingress/execution networks.
            from uuid import UUID
            try:
                placement = UUID(network["Labels"][DEPLOYMENT_LABEL])
                suffix = "-egress" if role=="egress" else "-public"
                expected = f"briareus-{node_uuid.hex}-{placement.hex}"+suffix
                valid = (placement.version==4 and network.get("Name")==expected
                    and network.get("Internal") is False and network.get("Driver")=="bridge"
                    and network["Labels"].get(NODE_LABEL)==str(node_uuid))
            except (ValueError, KeyError, TypeError):
                valid = False
            if not valid:
                raise EngineFailure("Unverified public execution network")
            continue
        if network.get("Internal") is not True or network.get("Labels", {}).get(NODE_LABEL) != str(node_uuid):
            raise EngineFailure("Unverified execution network")
        if network["Name"] not in attached:
            await engine.request("POST", f"/networks/{network['Id']}/connect", accepted=(200,),
                                 json={"Container": gateway_id})
    return gateway_id
