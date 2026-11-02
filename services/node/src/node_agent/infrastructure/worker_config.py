"""Render a fixed worker profile into a named Docker create payload."""

import os

from node_agent.docker_engine import EngineFailure, labels, network_name
from node_agent.runtime_profiles import (
    EGRESS_CPU,
    EGRESS_MEMORY,
    EGRESS_PIDS,
    EGRESS_REQUIRED,
    SUPERVISOR_MODULES,
    uses_direct_network,
    uses_egress,
)
from node_protocol import Deployment
from node_protocol.network_attestation import PublicNetworkAttestation

from .container_models import (
    ContainerConfiguration,
    ContainerHealthcheck,
    ContainerHost,
    EmptyOptions,
    LogConfiguration,
    VolumeMount,
    VolumeOptions,
)


def require_direct_network(spec: Deployment, grant: PublicNetworkAttestation | None) -> None:
    try:
        if grant is None:
            raise ValueError("Controller network attestation required")
        grant.require_placement(spec.node_uuid, spec.project_uuid, spec.id, spec.fingerprint)
    except ValueError as exc:
        raise EngineFailure(
            "Verified direct network policy bootstrap required before worker creation"
        ) from exc


def base_healthcheck(spec: Deployment) -> ContainerHealthcheck:
    return ContainerHealthcheck(
        test=[
            "CMD",
            "python",
            "-S",
            "-c",
            "import socket; "
            f"s=socket.create_connection(('127.0.0.1',{spec.release.port}),2); "
            f"s.sendall(b'GET {spec.release.health_path} HTTP/1.0\\r\\n"
            "Host: localhost\\r\\n\\r\\n'); "
            "assert s.makefile('rb').readline(128).split(b' ',2)[1]==b'200'; s.close()",
        ],
        interval=10_000_000_000,
        timeout=10_000_000_000,
        start_period=90_000_000_000,
        retries=3,
    )


def supervisor(spec: Deployment, config: ContainerConfiguration) -> None:
    module = spec.release.module
    if not spec.effect_verify_key or spec.release.run_as != "1000:1000":
        raise EngineFailure("Pinned authority and unprivileged command UID required")
    config.user = "0:0"
    config.command = ["/app/.venv/bin/python", "-m", module + "_hand.node_server"]
    if config.environment is None:
        config.environment = []
    config.environment.append("BRIAREUS_DEPLOYMENT=" + spec.model_dump_json())
    core_key = os.environ.get("BRIAREUS_CORE_VERIFY_KEY")
    if module == "web" and core_key:
        config.environment.append("BRIAREUS_CORE_VERIFY_KEY=" + core_key)
    host = config.host
    host.network_mode = (
        network_name(spec) + "-public"
        if uses_direct_network(spec)
        else network_name(spec)
        if uses_egress(spec)
        else "none"
    )
    host.cap_add = ["SETUID", "SETGID", "KILL"]
    host.binds = [
        f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway/workers/{spec.container_name}:/{module}-link:rw"
    ]
    if host.tmpfs is None:
        host.tmpfs = {}
    host.tmpfs.update(
        {
            "/var/lib/" + module + "-supervisor": "rw,nosuid,nodev,noexec,mode=0700,size=16777216",
            "/home/agent"
            if module == "terminal"
            else "/home/hand": "rw,nosuid,nodev,mode=0700,uid=1000,gid=1000,size=67108864",
        }
    )
    config.healthcheck = ContainerHealthcheck(
        test=[
            "CMD",
            "python",
            "-S",
            "-c",
            "import socket; "
            "s=socket.socket(socket.AF_UNIX); s.settimeout(2); "
            f"s.connect('/{module}-link/mcp.sock'); "
            "s.sendall(b'GET /health/ready HTTP/1.0\\r\\nHost: localhost\\r\\n\\r\\n'); "
            "assert s.makefile('rb').readline(128).split(b' ',2)[1]==b'200'; s.close()",
        ],
        interval=10_000_000_000,
        timeout=10_000_000_000,
        start_period=180_000_000_000,
        retries=3,
    )


def workspace(spec: Deployment, config: ContainerConfiguration) -> None:
    from node_agent.workspace_runtime import volume_name

    if spec.workspace is None:
        return
    if config.environment is None:
        config.environment = []
    config.environment.extend(
        [
            "BRIAREUS_NODE_UUID=" + str(spec.node_uuid),
            "BRIAREUS_PROJECT_UUID=" + str(spec.project_uuid),
            "BRIAREUS_PLACEMENT_UUID=" + str(spec.id),
            "BRIAREUS_WORKSPACE_UUID=" + str(spec.workspace.id),
        ]
    )
    config.host.mounts = [
        VolumeMount(
            source=volume_name(spec),
            target="/project-data",
            read_only=spec.workspace.read_only,
            options=VolumeOptions(subpath="data"),
        )
    ]
    module = spec.release.module
    if module == "files" and spec.effect_verify_key:
        config.command = ["/app/.venv/bin/python", "-m", "files_hand.node_server"]
        config.environment.append("BRIAREUS_DEPLOYMENT=" + spec.model_dump_json())
    if module in SUPERVISOR_MODULES:
        supervisor(spec, config)
    if module == "web":
        from node_agent.browser_seccomp import browser_seccomp_security_option

        config.host.security.append(browser_seccomp_security_option())
        config.host.mounts[0].target = "/browser"
        config.host.shm_size = 128 * 1024**2
    if spec.project_workspace is not None:
        config.host.mounts.append(
            VolumeMount(
                source=volume_name(spec, spec.project_workspace),
                target="/workspace/project",
                read_only=True if module == "reverse" else spec.project_workspace.read_only,
                options=VolumeOptions(subpath="data"),
            )
        )
        config.environment.append("BRIAREUS_PROJECT_TRANSFER=1")


def companion_budget(config: ContainerConfiguration) -> None:
    host = config.host
    host.memory -= EGRESS_MEMORY
    host.memory_swap -= EGRESS_MEMORY
    host.nano_cpus -= EGRESS_CPU * 1_000_000
    host.pids -= EGRESS_PIDS
    if host.memory < 64 * 1024**2 or host.nano_cpus < 100_000_000 or host.pids < 32:
        raise EngineFailure("Combined module budget must include its isolated egress helper")
    config.labels[EGRESS_REQUIRED] = "true"
    if config.environment is None:
        config.environment = []
    config.environment.extend(
        [
            "HTTP_PROXY=http://module-egress:8080",
            "HTTPS_PROXY=http://module-egress:8080",
            "NO_PROXY=",
        ]
    )


def worker_configuration(
    spec: Deployment, network_policy: PublicNetworkAttestation | None = None
) -> ContainerConfiguration:
    if uses_direct_network(spec):
        require_direct_network(spec, network_policy)
    if spec.release.module in SUPERVISOR_MODULES and spec.workspace is None:
        raise EngineFailure("Terminal requires an independently provisioned project workspace")
    config = ContainerConfiguration(
        image=spec.release.image,
        user=spec.release.run_as,
        labels=labels(spec).model_dump(by_alias=True),
        ports={f"{spec.release.port}/tcp": EmptyOptions()},
        healthcheck=base_healthcheck(spec),
        host=ContainerHost(
            network_mode=network_name(spec),
            memory=spec.limits.memory_bytes,
            memory_swap=spec.limits.memory_bytes,
            nano_cpus=spec.limits.cpu_millis * 1_000_000,
            pids=spec.limits.pids,
            tmpfs={"/tmp": "rw,nosuid,nodev,noexec,size=67108864"},  # noqa: S108 -- isolated container tmpfs mount target
            log=LogConfiguration(options={"max-size": "10m", "max-file": "2"}),
        ),
    )
    if spec.configuration is not None and spec.configuration.runtime_policy is not None:
        config.environment = [
            "BRIAREUS_RUNTIME_POLICY=" + spec.configuration.runtime_policy.model_dump_json()
        ]
    workspace(spec, config)
    if uses_egress(spec):
        companion_budget(config)
    return config
