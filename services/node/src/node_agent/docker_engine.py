"""Narrow dedicated rootless-engine client. No raw Docker passthrough.

The node runtime owns /run/briareus-node/docker.sock. Only Node Agent receives
that socket. Executors receive neither it nor the management network/secrets.
"""
from __future__ import annotations

import json
import asyncio
import os
import re
import stat
from uuid import UUID

import httpx

from node_protocol import Deployment
from .runtime_profiles import SUPERVISOR_MODULES, uses_egress, uses_direct_network, EGRESS_MEMORY, EGRESS_CPU, EGRESS_PIDS, EGRESS_REQUIRED

NODE_LABEL = "io.briareus.node"
DEPLOYMENT_LABEL = "io.briareus.deployment"
SPEC_LABEL = "io.briareus.spec"
PULL_TIMEOUT_SECONDS = 600


class EngineFailure(RuntimeError):
    def __init__(self, message, *, diagnostic=None):
        super().__init__(message)
        from node_protocol.diagnostics import diagnostic_wire
        from .diagnostics import REASONS
        self.diagnostic = diagnostic_wire(diagnostic) if diagnostic is not None else None
        self.reason = REASONS.get(message)


def labels(spec: Deployment) -> dict[str, str]:
    return {NODE_LABEL: str(spec.node_uuid), DEPLOYMENT_LABEL: str(spec.id),
            SPEC_LABEL: spec.fingerprint}


def network_name(spec: Deployment) -> str:
    # Per-deployment network, shared only with the node Gateway, never another
    # project's worker. Agent/Docker API have no listener on this bridge.
    return f"briareus-{spec.node_uuid.hex}-{spec.id.hex}"


def container_config(spec: Deployment, *, network_policy=None) -> dict:
    if uses_direct_network(spec):
        expected = {"profile":"public", "node_uuid":str(spec.node_uuid),
            "project_uuid":str(spec.project_uuid),"placement_uuid":str(spec.id),
            "fingerprint":spec.fingerprint,"ready":True}
        if (not isinstance(network_policy,dict)
            or any(network_policy.get(key)!=value for key,value in expected.items())
            or not re.fullmatch(r"[a-f0-9]{64}",network_policy.get("policy_sha256",""))):
            raise EngineFailure("Verified direct network policy bootstrap required before worker creation")
    if spec.release.module in SUPERVISOR_MODULES and spec.workspace is None:
        raise EngineFailure("Terminal requires an independently provisioned project workspace")
    config = {
        "Image": spec.release.image,
        "User": spec.release.run_as,
        "Labels": labels(spec),
        "ExposedPorts": {f"{spec.release.port}/tcp": {}},
        "Healthcheck": {
            "Test": ["CMD", "python", "-S", "-c", "import socket; "
                     f"s=socket.create_connection(('127.0.0.1',{spec.release.port}),2); "
                     f"s.sendall(b'GET {spec.release.health_path} HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n'); "
                     "assert s.makefile('rb').readline(128).split(b' ',2)[1]==b'200'; s.close()"],
            "Interval": 10_000_000_000, "Timeout": 10_000_000_000,
            "StartPeriod": 90_000_000_000, "Retries": 3,
        },
        "HostConfig": {
            "NetworkMode": network_name(spec),
            "Memory": spec.limits.memory_bytes,
            "MemorySwap": spec.limits.memory_bytes,
            "NanoCpus": spec.limits.cpu_millis * 1_000_000,
            "PidsLimit": spec.limits.pids,
            "CapDrop": ["ALL"],
            "SecurityOpt": ["no-new-privileges:true"],
            "ReadonlyRootfs": True,
            "Privileged": False,
            "PublishAllPorts": False,
            "RestartPolicy": {"Name": "no"},
            "Tmpfs": {"/tmp": "rw,nosuid,nodev,noexec,size=67108864"},
            "LogConfig": {"Type": "json-file", "Config": {"max-size": "10m", "max-file": "2"}},
        },
    }
    if spec.configuration is not None and spec.configuration.runtime_policy is not None:
        config.setdefault("Env", []).append("BRIAREUS_RUNTIME_POLICY="+spec.configuration.runtime_policy.model_dump_json())
    if spec.workspace is not None:
        from .workspace_runtime import volume_name
        config.setdefault("Env", []).extend(["BRIAREUS_NODE_UUID="+str(spec.node_uuid),
            "BRIAREUS_PROJECT_UUID="+str(spec.project_uuid), "BRIAREUS_PLACEMENT_UUID="+str(spec.id),
            "BRIAREUS_WORKSPACE_UUID="+str(spec.workspace.id)])
        config["HostConfig"]["Mounts"] = [{"Type":"volume", "Source":volume_name(spec),
            "Target":"/project-data", "ReadOnly":spec.workspace.read_only,
            "VolumeOptions":{"NoCopy":True,"Subpath":"data"}}]
        if spec.release.module == "files" and spec.effect_verify_key:
            config["Cmd"] = ["/app/.venv/bin/python", "-m", "files_hand.node_server"]
            config["Env"].append("BRIAREUS_DEPLOYMENT=" + spec.model_dump_json())
        module = spec.release.module
        if module in SUPERVISOR_MODULES:
            if not spec.effect_verify_key or spec.release.run_as != "1000:1000":
                raise EngineFailure("Pinned authority and unprivileged command UID required")
            config["User"] = "0:0"
            config["Cmd"] = ["/app/.venv/bin/python", "-m", module+"_hand.node_server"]
            config["Env"].append("BRIAREUS_DEPLOYMENT=" + spec.model_dump_json())
            config["HostConfig"].update({"NetworkMode": network_name(spec)+"-public" if uses_direct_network(spec) else network_name(spec) if uses_egress(spec) else "none",
                "CapAdd": ["SETUID", "SETGID", "KILL"],
                "Binds": [f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway/workers/{spec.container_name}:/{module}-link:rw"]})
            config["HostConfig"]["Tmpfs"].update({
                "/var/lib/"+module+"-supervisor": "rw,nosuid,nodev,noexec,mode=0700,size=16777216",
                "/home/agent" if module=="terminal" else "/home/hand":
                    "rw,nosuid,nodev,mode=0700,uid=1000,gid=1000,size=67108864"})
            config["Healthcheck"]["Test"] = ["CMD", "python", "-S", "-c", "import socket; "
                f"s=socket.socket(socket.AF_UNIX); s.settimeout(2); s.connect('/{module}-link/mcp.sock'); "
                "s.sendall(b'GET /health/ready HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n'); "
                "assert s.makefile('rb').readline(128).split(b' ',2)[1]==b'200'; s.close()"]
            config["Healthcheck"]["StartPeriod"] = 180_000_000_000
        if module == "web":
            from .browser_seccomp import browser_seccomp_security_option
            config["HostConfig"]["SecurityOpt"].append(browser_seccomp_security_option())
            config["HostConfig"]["Mounts"][0]["Target"] = "/browser"
            config["HostConfig"]["ShmSize"] = 128*1024**2
        if spec.project_workspace is not None:
            config["HostConfig"]["Mounts"].append({"Type":"volume", "Source":volume_name(spec,spec.project_workspace),
                "Target":"/workspace/project", "ReadOnly":True if module=="reverse" else spec.project_workspace.read_only,
                "VolumeOptions":{"NoCopy":True,"Subpath":"data"}})
            config["Env"].append("BRIAREUS_PROJECT_TRANSFER=1")
    if uses_egress(spec):
        host = config["HostConfig"]
        host["Memory"] -= EGRESS_MEMORY
        host["MemorySwap"] -= EGRESS_MEMORY
        host["NanoCpus"] -= EGRESS_CPU*1_000_000
        host["PidsLimit"] -= EGRESS_PIDS
        if host["Memory"]<64*1024**2 or host["NanoCpus"]<100_000_000 or host["PidsLimit"]<32:
            raise EngineFailure("Combined module budget must include its isolated egress helper")
        config["Labels"][EGRESS_REQUIRED] = "true"
        config.setdefault("Env", []).extend(["HTTP_PROXY=http://module-egress:8080",
            "HTTPS_PROXY=http://module-egress:8080", "NO_PROXY="])
    return config


class DockerEngine:
    def __init__(self, socket_path: str, *, allowed_registries: frozenset[str]):
        if socket_path != f"/run/user/{os.getuid()}/docker.sock" or os.getuid() < 2000:
            raise EngineFailure("Dedicated unprivileged runtime socket required")
        self.socket_path = socket_path
        self.allowed_registries = allowed_registries
        self.gateway_id = None
        self.utility_image = None
        self.workspace_cleanup_uncertain = False
        self.network_attestations = {}
        configured_controls = os.environ.get("BRIAREUS_NETWORK_CONTROL_ADDRESSES")
        self.control_addresses = ()
        if configured_controls is not None:
            import ipaddress
            try:
                values = json.loads(configured_controls)
                if (not isinstance(values,list) or not 1<=len(values)<=128
                    or any(not isinstance(value,str) or str(ipaddress.ip_address(value))!=value for value in values)
                    or len(set(values))!=len(values)):
                    raise ValueError("Invalid deny set")
                self.control_addresses = tuple(values)
            except (ValueError,TypeError):
                raise EngineFailure("Explicit canonical Node/Core network deny addresses required") from None
        self.client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://node-engine/v1.51", timeout=30, trust_env=False,
        )

    async def close(self):
        await self.client.aclose()

    async def request(self, method: str, path: str, *, accepted=(200,), **kwargs):
        try:
            response = await self.client.request(method, path, **kwargs)
        except httpx.HTTPError:
            raise EngineFailure("Inner Docker engine unavailable") from None
        if response.status_code not in accepted:
            # Engine error text may include private paths/credentials.
            raise EngineFailure("Inner Docker operation rejected")
        return response

    async def containers(self, node_uuid):
        if not isinstance(node_uuid, UUID) or node_uuid.version != 4:
            raise EngineFailure("Node UUIDv4 required")
        response = await self.request("GET", "/containers/json", params={
            "all": "true", "filters": json.dumps({"label": [f"{NODE_LABEL}={node_uuid}", DEPLOYMENT_LABEL]}),
        })
        return response.json()

    async def verify_rootless(self):
        if self.workspace_cleanup_uncertain:
            raise EngineFailure("Workspace helper recovery requires controller restart")
        metadata = os.stat(self.socket_path)
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise EngineFailure("Rootless socket ownership mismatch")
        info = (await self.request("GET", "/info")).json()
        if ("name=rootless" not in info.get("SecurityOptions", [])
            or info.get("CgroupVersion") != "2" or info.get("CgroupDriver") != "systemd"
            or info.get("DockerRootDir") == "/var/lib/docker"
            or info.get("MemoryLimit") is not True or info.get("PidsLimit") is not True
            or info.get("CpuCfsQuota") is not True):
            raise EngineFailure("Rootless runtime with enforceable cgroup quotas required")

    async def pull(self, spec: Deployment):
        await self.pull_image(spec.release.image)

    async def pull_image(self, image: str):
        if not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", image):
            raise EngineFailure("Immutable image digest required")
        registry = image.split("/", 1)[0]
        if registry not in self.allowed_registries:
            raise EngineFailure("Image registry is not approved for this node")
        try:
            # A read timeout resets on every progress chunk. Also bound the
            # complete delivery phase so endless progress cannot retain it.
            async with asyncio.timeout(PULL_TIMEOUT_SECONDS):
                async with self.client.stream("POST", "/images/create", params={
                    "fromImage": image,
                }, timeout=httpx.Timeout(PULL_TIMEOUT_SECONDS, connect=5)) as response:
                    if response.status_code != 200:
                        raise EngineFailure("Approved image pull rejected")
                    size = 0
                    async for line in response.aiter_lines():
                        size += len(line)
                        if size > 8_000_000 or len(line) > 65_536:
                            raise EngineFailure("Image pull response exceeds budget")
                        if line and "error" in json.loads(line):
                            raise EngineFailure("Approved image pull failed")
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise EngineFailure("Approved image delivery unavailable") from None

    async def inspect(self, container_id: str):
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise EngineFailure("Exact container identity required")
        response = await self.request("GET", f"/containers/{container_id}/json", accepted=(200, 404))
        return response.json() if response.status_code == 200 else None

    async def remove_target(self, spec: Deployment, container_id: str):
        """Bounded stop and removal of one owned placement, preserving volumes."""
        current = await self.inspect(container_id)
        if current is None:
            return
        actual = current.get("Config", {}).get("Labels", {})
        if (actual.get(NODE_LABEL) != str(spec.node_uuid)
            or actual.get(DEPLOYMENT_LABEL) != str(spec.id)):
            raise EngineFailure("Refusing to stop a foreign placement")
        from .egress_runtime import remove_companion
        await self.request("POST", f"/containers/{container_id}/stop", params={"t": 15},
                           accepted=(204, 304, 404))
        # If stopping the main is rejected, its working network companion
        # must remain intact. Never dismantle a still-running placement first.
        await remove_companion(self, spec, current)
        await self.request("DELETE", f"/containers/{container_id}", accepted=(204, 404))

    async def resume_applied(self,spec:Deployment) -> str:
        """Only Controller's fresh signed Apply + exact journal proof calls this."""
        return await self.stage(spec,resume_stopped=True)

    async def stage(self, spec: Deployment, *, resume_stopped=False) -> str:
        """Create/start the target only, after its previous instance was removed.

        The exact digest must already be pulled by the approved release flow.
        A failed start leaves the labelled candidate for reconciliation.
        """
        if not spec.enabled:
            raise EngineFailure("Disabled deployment cannot be staged")
        if self.gateway_id is None:
            raise EngineFailure("Private Node Gateway must be provisioned before workers")
        from .egress_runtime import ensure_execution_network, ensure_egress
        if spec.release.module not in SUPERVISOR_MODULES or uses_egress(spec):
            await ensure_execution_network(self, spec)
        if uses_direct_network(spec):
            from .network_policy_runtime import prepare_direct_network
            self.network_attestations[spec.container_name] = await prepare_direct_network(self,spec)
        # Deterministic name makes retries after lost responses nonduplicating.
        previous = [item for item in await self.containers(spec.node_uuid)
                    if "/" + spec.container_name in item.get("Names", [])]
        if previous:
            if len(previous) != 1 or any(
                previous[0].get("Labels", {}).get(key) != value
                for key, value in labels(spec).items()
            ):
                raise EngineFailure("Conflicting candidate; refusing adoption")
            stopped=previous[0].get("State")!="running"
            if stopped and not resume_stopped:
                raise EngineFailure("Candidate stopped; explicit recovery required")
            if stopped:
                current=await self.inspect(previous[0]["Id"])
                if (not current or current.get("State",{}).get("Status") not in {"exited","created"}
                    or any(current.get("Config",{}).get("Labels",{}).get(key)!=value for key,value in labels(spec).items())):
                    raise EngineFailure("Applied instance changed during recovery")
            if uses_egress(spec):
                # Recovery of an exact immutable existing instance must also
                # restore its missing companion; returning its ID alone is
                # not proof that the complete placement is usable.
                await ensure_egress(self, spec)
            if stopped:
                await self.request("POST",f"/containers/{previous[0]['Id']}/start",accepted=(204,304))
            return previous[0]["Id"]
        from .workspace_runtime import prepare_workspace
        await prepare_workspace(self, spec)
        created = await self.request("POST", "/containers/create", accepted=(201,),
                                     params={"name": spec.container_name}, json=container_config(spec,network_policy=self.network_attestations.get(spec.container_name)))
        container_id = created.json()["Id"]
        try:
            if uses_egress(spec):
                await ensure_egress(self, spec)
            await self.request("POST", f"/containers/{container_id}/start", accepted=(204,))
        except EngineFailure:
            # Reap only the newly-created exact owned pair. Failed setup must
            # not strand an invisible egress allocation before journaling.
            await self.remove_target(spec,container_id)
            raise
        return container_id
