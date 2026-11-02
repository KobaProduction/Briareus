"""Narrow dedicated rootless-engine client. No raw Docker passthrough.

The node runtime owns /run/briareus-node/docker.sock. Only Node Agent receives
that socket. Executors receive neither it nor the management network/secrets.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import stat
from uuid import UUID

import httpx
from pydantic import TypeAdapter

from node_protocol import Deployment
from node_protocol.diagnostics import FailureDiagnostic
from node_protocol.network_attestation import PublicNetworkAttestation

from .domain.worker_stage import WorkerStageFailure
from .infrastructure.container_models import (
    ContainerConfiguration,
    ContainerInspection,
    ContainerSummary,
    PlacementLabels,
    PullProgress,
    RootlessEngineInfo,
)
from .infrastructure.docker_commands import NetworkConnect, NetworkCreate, VolumeCreate
from .runtime_profiles import uses_egress

NODE_LABEL = "io.briareus.node"
DEPLOYMENT_LABEL = "io.briareus.deployment"
SPEC_LABEL = "io.briareus.spec"
PULL_TIMEOUT_SECONDS = 600


class EngineFailure(WorkerStageFailure):
    def __init__(self, message: str, *, diagnostic: FailureDiagnostic | None = None) -> None:
        super().__init__(message)
        from .diagnostics import REASONS

        self.diagnostic = diagnostic
        self.reason = REASONS.get(message)


def labels(spec: Deployment) -> PlacementLabels:
    return PlacementLabels(
        node=str(spec.node_uuid), deployment=str(spec.id), fingerprint=spec.fingerprint
    )


def network_name(spec: Deployment) -> str:
    # Per-deployment network, shared only with the node Gateway, never another
    # project's worker. Agent/Docker API have no listener on this bridge.
    return f"briareus-{spec.node_uuid.hex}-{spec.id.hex}"


def container_config(
    spec: Deployment, *, network_policy: PublicNetworkAttestation | None = None
) -> ContainerConfiguration:
    from .infrastructure.worker_config import worker_configuration

    return worker_configuration(spec, network_policy)


class DockerEngine:
    def __init__(self, socket_path: str, *, allowed_registries: frozenset[str]) -> None:
        if socket_path != f"/run/user/{os.getuid()}/docker.sock" or os.getuid() < 2000:
            raise EngineFailure("Dedicated unprivileged runtime socket required")
        self.socket_path = socket_path
        self.allowed_registries = allowed_registries
        self.gateway_id: str | None = None
        self.utility_image: str | None = None
        self.workspace_cleanup_uncertain = False
        self.network_policy_cleanup_uncertain = False
        self.network_attestations: dict[str, PublicNetworkAttestation] = {}
        configured_controls = os.environ.get("BRIAREUS_NETWORK_CONTROL_ADDRESSES")
        self.control_addresses: tuple[str, ...] = ()
        if configured_controls is not None:
            import ipaddress

            try:
                values = TypeAdapter(list[str]).validate_json(configured_controls, strict=True)
                if (
                    not 1 <= len(values) <= 128
                    or any(str(ipaddress.ip_address(value)) != value for value in values)
                    or len(set(values)) != len(values)
                ):
                    raise ValueError("Invalid deny set")
                self.control_addresses = tuple(values)
            except (ValueError, TypeError):
                raise EngineFailure(
                    "Explicit canonical Node/Core network deny addresses required"
                ) from None
        self.client = httpx.AsyncClient(
            transport=httpx.AsyncHTTPTransport(uds=socket_path),
            base_url="http://node-engine/v1.51",
            timeout=30,
            trust_env=False,
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def request(
        self,
        method: str,
        path: str,
        *,
        accepted: tuple[int, ...] = (200,),
        params: dict[str, str | int] | None = None,
        payload: ContainerConfiguration
        | NetworkCreate
        | NetworkConnect
        | VolumeCreate
        | None = None,
    ) -> httpx.Response:
        try:
            response = await self.client.request(
                method,
                path,
                params=params,
                json=payload.model_dump(mode="json", by_alias=True, exclude_none=True)
                if payload is not None
                else None,
            )
        except httpx.HTTPError:
            raise EngineFailure("Inner Docker engine unavailable") from None
        if response.status_code not in accepted:
            # Engine error text may include private paths/credentials.
            raise EngineFailure("Inner Docker operation rejected")
        return response

    async def containers(self, node_uuid: UUID) -> tuple[ContainerSummary, ...]:
        if node_uuid.version != 4:
            raise EngineFailure("Node UUIDv4 required")
        response = await self.request(
            "GET",
            "/containers/json",
            params={
                "all": "true",
                "filters": json.dumps({"label": [f"{NODE_LABEL}={node_uuid}", DEPLOYMENT_LABEL]}),
            },
        )
        return tuple(TypeAdapter(list[ContainerSummary]).validate_python(response.json()))

    async def verify_rootless(self) -> None:
        if self.workspace_cleanup_uncertain:
            raise EngineFailure("Workspace helper recovery requires controller restart")
        metadata = os.stat(self.socket_path)
        if not stat.S_ISSOCK(metadata.st_mode) or metadata.st_uid != os.getuid():
            raise EngineFailure("Rootless socket ownership mismatch")
        info = RootlessEngineInfo.model_validate((await self.request("GET", "/info")).json())
        if (
            "name=rootless" not in info.security
            or info.cgroup_version != "2"
            or info.cgroup_driver != "systemd"
            or info.root_directory == "/var/lib/docker"
            or info.memory_limit is not True
            or info.pids_limit is not True
            or info.cpu_quota is not True
        ):
            raise EngineFailure("Rootless runtime with enforceable cgroup quotas required")

    async def pull(self, spec: Deployment) -> None:
        await self.pull_image(spec.release.image)

    async def pull_image(self, image: str) -> None:
        if not re.fullmatch(r"[a-z0-9][a-z0-9./:_-]*@sha256:[a-f0-9]{64}", image):
            raise EngineFailure("Immutable image digest required")
        registry = image.split("/", 1)[0]
        if registry not in self.allowed_registries:
            raise EngineFailure("Image registry is not approved for this node")
        try:
            # A read timeout resets on every progress chunk. Also bound the
            # complete delivery phase so endless progress cannot retain it.
            async with asyncio.timeout(PULL_TIMEOUT_SECONDS):
                async with self.client.stream(
                    "POST",
                    "/images/create",
                    params={
                        "fromImage": image,
                    },
                    timeout=httpx.Timeout(PULL_TIMEOUT_SECONDS, connect=5),
                ) as response:
                    if response.status_code != 200:
                        raise EngineFailure("Approved image pull rejected")
                    size = 0
                    processed = 0
                    async for line in response.aiter_lines():
                        size += len(line)
                        if size > 8_000_000 or len(line) > 65_536:
                            raise EngineFailure("Image pull response exceeds budget")
                        if (
                            line
                            and "error" in PullProgress.model_validate_json(line).model_fields_set
                        ):
                            raise EngineFailure("Approved image pull failed")
                        processed += 1
                        if processed % 64 == 0:
                            # Buffered progress can otherwise starve the fenced writer heartbeat.
                            await asyncio.sleep(0)
        except (httpx.HTTPError, ValueError, TimeoutError):
            raise EngineFailure("Approved image delivery unavailable") from None

    async def inspect(self, container_id: str) -> ContainerInspection | None:
        if not re.fullmatch(r"[a-f0-9]{64}", container_id):
            raise EngineFailure("Exact container identity required")
        response = await self.request(
            "GET", f"/containers/{container_id}/json", accepted=(200, 404)
        )
        return (
            ContainerInspection.model_validate(response.json())
            if response.status_code == 200
            else None
        )

    async def remove_target(self, spec: Deployment, container_id: str) -> None:
        """Bounded stop and removal of one owned placement, preserving volumes."""
        current = await self.inspect(container_id)
        if current is None:
            return
        actual = current.config.labels
        if actual.get(NODE_LABEL) != str(spec.node_uuid) or actual.get(DEPLOYMENT_LABEL) != str(
            spec.id
        ):
            raise EngineFailure("Refusing to stop a foreign placement")
        from .egress_runtime import remove_companion

        await self.request(
            "POST", f"/containers/{container_id}/stop", params={"t": 15}, accepted=(204, 304, 404)
        )
        # If stopping the main is rejected, its working network companion
        # must remain intact. Never dismantle a still-running placement first.
        await remove_companion(self, spec, current)
        await self.request("DELETE", f"/containers/{container_id}", accepted=(204, 404))

    async def resume_applied(self, spec: Deployment) -> str:
        """Only Controller's fresh signed Apply + exact journal proof calls this."""
        return await self.stage(spec, resume_stopped=True)

    async def stage(self, spec: Deployment, *, resume_stopped: bool = False) -> str:
        from .application.worker_stage import StageWorker
        from .infrastructure.worker_stage import DockerWorkerStage

        try:
            return await StageWorker(
                DockerWorkerStage(self, spec), needs_companion=uses_egress(spec)
            ).execute(
                enabled=spec.enabled,
                gateway_available=self.gateway_id is not None,
                resume_stopped=resume_stopped,
            )
        except EngineFailure:
            raise
        except WorkerStageFailure as exc:
            raise EngineFailure(str(exc)) from exc
