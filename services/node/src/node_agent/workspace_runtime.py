"""Named project volumes; no caller-selected host path or driver option."""
import asyncio
import hashlib
import json
from uuid import UUID

from node_protocol.control import canonical
from .docker_engine import NODE_LABEL, EngineFailure
from .runtime_profiles import SUPERVISOR_MODULES

PROJECT_LABEL = "io.briareus.project"
WORKSPACE_LABEL = "io.briareus.workspace"
ROLE = "io.briareus.role"
CONFIG = "io.briareus.workspace-init-config"


def helper_labels_match(actual, expected):
    # Docker merges image labels with requested container labels. OCI build
    # metadata is harmless, but every Briareus ownership label must be exact.
    return (isinstance(actual,dict) and all(actual.get(key)==value for key,value in expected.items())
        and {key for key in actual if key.startswith("io.briareus.")}==set(expected))


def volume_name(spec, workspace=None):
    workspace = workspace if workspace is not None else spec.workspace
    if workspace is None:
        raise ValueError("Explicit workspace binding required")
    return f"briareus-{spec.node_uuid.hex}-{spec.project_uuid.hex}-{workspace.id.hex}"


def workspace_labels(spec, workspace=None):
    workspace = workspace if workspace is not None else spec.workspace
    return {NODE_LABEL:str(spec.node_uuid), PROJECT_LABEL:str(spec.project_uuid),
            WORKSPACE_LABEL:str(workspace.id), ROLE:"project-workspace"}


def initializer_config(spec, image, attestation=None, *, workspace=None):
    workspace = workspace if workspace is not None else spec.workspace
    identity = {"labels":workspace_labels(spec,workspace), "image":image}
    if spec.release.module in SUPERVISOR_MODULES:
        identity["runtime_worker"] = spec.container_name
    if attestation is not None:
        from .workspace_init import validate_attestation
        validate_attestation(attestation, {"node_uuid":str(spec.node_uuid), "project_uuid":str(spec.project_uuid)}, spec.container_name)
        identity["network_policy"] = attestation
    fingerprint = hashlib.sha256(canonical(identity)).hexdigest()
    config = {"Image":image,"User":"0:0","Cmd":["/app/.venv/bin/python","-m","node_agent.workspace_init"],
        "Env":["BRIAREUS_NODE_UUID="+str(spec.node_uuid),"BRIAREUS_PROJECT_UUID="+str(spec.project_uuid),
               "BRIAREUS_WORKSPACE_UUID="+str(workspace.id)],
        "Labels":{**workspace_labels(spec,workspace), ROLE:"workspace-initializer", CONFIG:fingerprint},
        "HostConfig":{"NetworkMode":"none","ReadonlyRootfs":True,"Privileged":False,
            "CapDrop":["ALL"],"CapAdd":["CHOWN"],"SecurityOpt":["no-new-privileges:true"],
            "Memory":64*1024**2,"MemorySwap":64*1024**2,"NanoCpus":200_000_000,"PidsLimit":32,
            "RestartPolicy":{"Name":"no"},"PublishAllPorts":False,
            "Mounts":[{"Type":"volume","Source":volume_name(spec,workspace),"Target":"/workspace",
                       "ReadOnly":False,"VolumeOptions":{"NoCopy":True}}],
            "LogConfig":{"Type":"json-file","Config":{"max-size":"1m","max-file":"1"}}}}
    if spec.release.module in SUPERVISOR_MODULES:
        config["Env"].append("BRIAREUS_RUNTIME_WORKER=" + spec.container_name)
        config["HostConfig"]["Binds"] = [f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway:/node-link:rw"]
    if attestation is not None:
        if spec.release.module not in SUPERVISOR_MODULES:
            raise ValueError("Network attestation requires a private supervisor link")
        config["Env"].append("BRIAREUS_NETWORK_POLICY_ATTESTATION=" + canonical(attestation).decode())
    return config


async def prepare_workspace(engine, spec):
    for workspace in (spec.workspace, spec.project_workspace):
        if workspace is not None:
            await _prepare_workspace(engine, spec, workspace)


async def _prepare_workspace(engine, spec, workspace):
    if engine.workspace_cleanup_uncertain:
        raise EngineFailure("Workspace helper cleanup is unresolved")
    image = engine.utility_image
    if image is None:
        raise EngineFailure("Approved initializer image is not configured")
    name = volume_name(spec,workspace)
    labels = workspace_labels(spec,workspace)
    response = await engine.request("GET", f"/volumes/{name}", accepted=(200,404))
    if response.status_code == 404:
        await engine.request("POST", "/volumes/create", accepted=(201,), json={
            "Name":name,"Driver":"local","Labels":labels})
        response = await engine.request("GET", f"/volumes/{name}")
    volume = response.json()
    if (volume.get("Name") != name or volume.get("Driver") != "local" or volume.get("Options") not in (None,{})
        or any(volume.get("Labels",{}).get(key) != value for key,value in labels.items())):
        raise EngineFailure("Refusing foreign or host-backed workspace volume")
    attestation = getattr(engine, "network_attestations", {}).get(spec.container_name)
    config = initializer_config(spec,image,attestation,workspace=workspace)
    helper_name = "briareus-workspace-init-"+workspace.id.hex
    response = await engine.request("GET", "/containers/json", params={"all":"true",
        "filters":json.dumps({"name":[helper_name]})})
    exact = [item for item in response.json() if "/"+helper_name in item.get("Names",[])]
    if len(exact)>1 or any(not helper_labels_match(item.get("Labels"),config["Labels"]) for item in exact):
        raise EngineFailure("Conflicting workspace initializer; explicit recovery required")
    if exact:
        container = exact[0]["Id"]
    else:
        response = await engine.request("POST", "/containers/create", accepted=(201,),
            params={"name":helper_name},json=config)
        container = response.json()["Id"]
    try:
        async with asyncio.timeout(15):
            current = await engine.inspect(container)
            state = current.get("State",{}) if current else {}
            if state.get("Status") == "created":
                await engine.request("POST",f"/containers/{container}/start",accepted=(204,304))
            response = await engine.request("POST",f"/containers/{container}/wait",params={"condition":"not-running"})
            result = response.json()
            if type(result.get("StatusCode")) is not int or result["StatusCode"] != 0 or result.get("Error"):
                from .diagnostics import state_diagnostic
                failed = await engine.inspect(container)
                raise EngineFailure("Workspace initialization refused", diagnostic=state_diagnostic(
                    "creating",failed.get("State",{}) if failed else {},component="engine"))
    except TimeoutError:
        raise EngineFailure("Workspace initializer exceeded its deadline") from None
    finally:
        # Only this owned helper may be stopped. No volume deletion, recursive
        # chown, project data overwrite or unrelated worker restart exists here.
        try:
            async with asyncio.timeout(5):
                current = await engine.inspect(container)
                if current:
                    if not helper_labels_match(current.get("Config",{}).get("Labels"),config["Labels"]):
                        raise EngineFailure("Workspace helper identity changed")
                    if current.get("State",{}).get("Running"):
                        await engine.request("POST",f"/containers/{container}/stop",params={"t":1},accepted=(204,304,404))
                    await engine.request("DELETE",f"/containers/{container}",accepted=(204,404))
        except (TimeoutError, EngineFailure):
            engine.workspace_cleanup_uncertain = True
            raise EngineFailure("Workspace helper cleanup is unresolved") from None


async def recover_workspace_helpers(engine, node_uuid):
    """Single journal owner reaps only its interrupted one-shot initializers."""
    response = await engine.request("GET", "/containers/json", params={"all":"true", "filters":json.dumps({
        "label":[f"{NODE_LABEL}={node_uuid}",f"{ROLE}=workspace-initializer"]})})
    for item in response.json():
        labels = item.get("Labels",{})
        try:
            workspace, project = UUID(labels[WORKSPACE_LABEL]), UUID(labels[PROJECT_LABEL])
            if (workspace.version != 4 or project.version != 4 or labels.get(NODE_LABEL) != str(node_uuid)
                or labels.get(ROLE) != "workspace-initializer"
                or "/briareus-workspace-init-"+workspace.hex not in item.get("Names",[])):
                raise ValueError("Unverified initializer")
        except (ValueError,KeyError):
            raise EngineFailure("Refusing to reap an unverified workspace helper") from None
        container = item["Id"]
        current = await engine.inspect(container)
        if not current or current.get("Config",{}).get("Labels") != labels:
            raise EngineFailure("Workspace helper changed during recovery")
        async with asyncio.timeout(5):
            if current.get("State",{}).get("Running"):
                await engine.request("POST",f"/containers/{container}/stop",params={"t":1},accepted=(204,304,404))
            await engine.request("DELETE",f"/containers/{container}",accepted=(204,404))
    engine.workspace_cleanup_uncertain = False
