"""Placement-private public egress; no host engine, credentials or Core route."""
import json
import re
from .docker_engine import NODE_LABEL, DEPLOYMENT_LABEL, SPEC_LABEL, EngineFailure, labels, network_name
from .runtime_profiles import ROLE_LABEL, EGRESS_REQUIRED, EGRESS_MEMORY, EGRESS_CPU, EGRESS_PIDS


def companion_name(container_name):
    if not re.fullmatch(r"briareus-[a-f0-9]{48}", container_name):
        raise EngineFailure("Derived placement name required")
    return container_name + "-egress"


async def ensure_network(engine, spec, name, *, internal, role=None):
    expected = {NODE_LABEL:str(spec.node_uuid), DEPLOYMENT_LABEL:str(spec.id)}
    if role:
        expected[ROLE_LABEL] = role
    rows = (await engine.request("GET", "/networks", params={"filters":json.dumps({"name":[name]})})).json()
    exact = [row for row in rows if row.get("Name")==name]
    if not exact:
        from .network_addressing import bridge_ipam
        await engine.request("POST", "/networks/create", accepted=(201,), json={
            "Name":name, "Driver":"bridge", "Internal":internal, "EnableIPv6":False, "Labels":expected,
            "IPAM":await bridge_ipam(engine,name)})
    elif (len(exact)!=1 or exact[0].get("Internal") is not internal
          or exact[0].get("Driver")!="bridge"
          or any(exact[0].get("Labels",{}).get(key)!=value for key,value in expected.items())):
        raise EngineFailure("Conflicting placement network; refusing adoption")
    else:
        from .network_addressing import validate_network_addresses
        validate_network_addresses(engine,exact[0])


async def ensure_execution_network(engine, spec):
    name = network_name(spec)
    await ensure_network(engine, spec, name, internal=True)
    gateway = await engine.inspect(engine.gateway_id)
    if not gateway:
        raise EngineFailure("Private Gateway unavailable")
    if name not in gateway.get("NetworkSettings",{}).get("Networks",{}):
        await engine.request("POST", f"/networks/{name}/connect", json={"Container":engine.gateway_id})


def companion_config(spec, image):
    expected = {**labels(spec), ROLE_LABEL:"egress"}
    network = network_name(spec)
    return {"Image":image, "User":"1000:1000", "Labels":expected,
        "Cmd":["/app/.venv/bin/python", "-m", "gateway_runtime.egress_proxy"],
        "Healthcheck":{"Test":["CMD", "python", "-S", "-c",
            "import socket; s=socket.create_connection(('127.0.0.1',8080),2); "
            "s.sendall(b'GET /health/ready HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n'); "
            "line=s.makefile('rb').readline(128); s.close(); "
            "assert line.startswith((b'HTTP/1.0 ',b'HTTP/1.1 ')) and line.split(b' ',2)[1]==b'200'"],
            "Interval":10_000_000_000,"Timeout":8_000_000_000,"StartPeriod":20_000_000_000,"Retries":3},
        "NetworkingConfig":{"EndpointsConfig":{network:{"Aliases":["module-egress","web-egress"]}}},
        "HostConfig":{"NetworkMode":network,"Memory":EGRESS_MEMORY,"MemorySwap":EGRESS_MEMORY,
            "NanoCpus":EGRESS_CPU*1_000_000,"PidsLimit":EGRESS_PIDS,"CapDrop":["ALL"],
            "SecurityOpt":["no-new-privileges:true"],"ReadonlyRootfs":True,"Privileged":False,
            "PublishAllPorts":False,"RestartPolicy":{"Name":"no"},
            "Tmpfs":{"/tmp":"rw,nosuid,nodev,noexec,size=8388608"},
            "LogConfig":{"Type":"json-file","Config":{"max-size":"2m","max-file":"1"}}}}


async def ensure_egress(engine, spec):
    if not engine.utility_image:
        raise EngineFailure("Pinned egress runtime image required")
    name = companion_name(spec.container_name)
    external = network_name(spec)+"-egress"
    await ensure_network(engine, spec, external, internal=False, role="egress")
    expected = {**labels(spec), ROLE_LABEL:"egress"}
    desired = companion_config(spec, engine.utility_image)
    exact = [row for row in await engine.containers(spec.node_uuid) if "/"+name in row.get("Names",[])]
    if exact:
        if len(exact)!=1 or any(exact[0].get("Labels",{}).get(key)!=value for key,value in expected.items()):
            raise EngineFailure("Conflicting placement egress; refusing adoption")
        helper = exact[0]["Id"]
        current = await engine.inspect(helper)
        if (not current or current.get("Name")!="/"+name
            or any(current.get("Config",{}).get("Labels",{}).get(key)!=value for key,value in expected.items())):
            raise EngineFailure("Refusing foreign placement egress replacement")
        if current.get("Config",{}).get("Healthcheck") != desired["Healthcheck"]:
            # Container labels are immutable; inspect its exact ID before any
            # mutation. Replace only the owned helper, preserving the main.
            await engine.request("POST", f"/containers/{helper}/stop", params={"t":3},accepted=(204,304,404))
            await engine.request("DELETE", f"/containers/{helper}",accepted=(204,404))
            exact = []
    if not exact:
        created = await engine.request("POST", "/containers/create", accepted=(201,), params={"name":name},
            json=desired)
        helper = created.json()["Id"]
    current = await engine.inspect(helper)
    if not current:
        raise EngineFailure("Placement egress unavailable")
    if external not in current.get("NetworkSettings",{}).get("Networks",{}):
        await engine.request("POST", f"/networks/{external}/connect", json={"Container":helper})
    await engine.request("POST", f"/containers/{helper}/start", accepted=(204,304))
    return helper


async def remove_companion(engine, spec, main):
    metadata = main.get("Config",{}).get("Labels",{})
    if metadata.get(ROLE_LABEL)=="egress":
        return
    if metadata.get(EGRESS_REQUIRED)!="true":
        return
    name = companion_name(main.get("Name", "").removeprefix("/"))
    exact = [row for row in await engine.containers(spec.node_uuid) if "/"+name in row.get("Names",[])]
    if len(exact)>1:
        raise EngineFailure("Ambiguous placement egress")
    if not exact:
        return
    helper = await engine.inspect(exact[0]["Id"])
    actual = helper.get("Config",{}).get("Labels",{}) if helper else {}
    if any(actual.get(key)!=metadata.get(key) for key in (NODE_LABEL, DEPLOYMENT_LABEL, SPEC_LABEL)) or actual.get(ROLE_LABEL)!="egress":
        raise EngineFailure("Refusing foreign placement egress removal")
    await engine.request("POST", f"/containers/{exact[0]['Id']}/stop", params={"t":3},accepted=(204,304,404))
    await engine.request("DELETE", f"/containers/{exact[0]['Id']}", accepted=(204,404))
