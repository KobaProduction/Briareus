"""Owned volume/helper adapter; no caller-selected host paths or driver options."""

import asyncio
import hashlib
import json
from collections.abc import Mapping
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from node_agent.infrastructure.runtime_bindings import _DeploymentBinding
from node_protocol import Deployment
from node_protocol.control import canonical
from node_protocol.models import WorkspaceMount
from node_protocol.network_attestation import PublicNetworkAttestation

from .application.workspace import PrepareWorkspaces
from .diagnostics import state_diagnostic
from .docker_engine import NODE_LABEL, EngineFailure
from .domain.workspace import WorkspaceIdentity
from .domain.workspace import helper_labels_match as owned_labels_match
from .infrastructure.container_models import (
    ContainerConfiguration,
    ContainerCreated,
    ContainerExit,
    ContainerHost,
    ContainerSummary,
    InspectedState,
    LogConfiguration,
    VolumeInspection,
    VolumeMount,
)
from .infrastructure.docker_commands import VolumeCreate
from .infrastructure.docker_records import ContainerObservationPort
from .infrastructure.docker_request import DockerRequestPort
from .runtime_profiles import SUPERVISOR_MODULES

PROJECT_LABEL = "io.briareus.project"
WORKSPACE_LABEL = "io.briareus.workspace"
ROLE = "io.briareus.role"
CONFIG = "io.briareus.workspace-init-config"


class WorkspaceEngine(DockerRequestPort, ContainerObservationPort, Protocol):
    utility_image: str | None
    workspace_cleanup_uncertain: bool
    network_attestations: dict[str, PublicNetworkAttestation]


class WorkspaceOwnership(BaseModel):
    model_config = ConfigDict(strict=True, populate_by_name=True)
    node: str = Field(alias=NODE_LABEL)
    project: str = Field(alias=PROJECT_LABEL)
    workspace: str = Field(alias=WORKSPACE_LABEL)
    role: str = Field(default="project-workspace", alias=ROLE)


class InitializerIdentity(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid", frozen=True)
    labels: WorkspaceOwnership
    image: str
    runtime_worker: str | None = None
    network_policy: PublicNetworkAttestation | None = None


def helper_labels_match(actual: object, expected: Mapping[str, str]) -> bool:
    if not isinstance(actual, dict) or any(
        not isinstance(key, str) or not isinstance(value, str) for key, value in actual.items()
    ):
        return False
    return owned_labels_match(actual, expected)


def bound_workspace(spec: Deployment, workspace: WorkspaceMount | None) -> WorkspaceMount:
    selected = workspace if workspace is not None else spec.workspace
    if selected is None:
        raise ValueError("Explicit workspace binding required")
    return selected


def workspace_identity(spec: Deployment, workspace: WorkspaceMount) -> WorkspaceIdentity:
    return WorkspaceIdentity(spec.node_uuid, spec.project_uuid, workspace.id)


def volume_name(spec: Deployment, workspace: WorkspaceMount | None = None) -> str:
    return workspace_identity(spec, bound_workspace(spec, workspace)).volume_name


def workspace_labels(
    spec: Deployment, workspace: WorkspaceMount | None = None
) -> WorkspaceOwnership:
    selected = bound_workspace(spec, workspace)
    return WorkspaceOwnership(
        node=str(spec.node_uuid), project=str(spec.project_uuid), workspace=str(selected.id)
    )


def initializer_config(
    spec: Deployment,
    image: str,
    attestation: PublicNetworkAttestation | None = None,
    *,
    workspace: WorkspaceMount | None = None,
) -> ContainerConfiguration:
    selected = bound_workspace(spec, workspace)
    ownership = workspace_labels(spec, selected)
    supervised = spec.release.module in SUPERVISOR_MODULES
    if attestation is not None:
        from .workspace_init import validate_attestation

        validate_attestation(
            attestation,
            spec.node_uuid,
            spec.project_uuid,
            spec.container_name,
        )
    identity = InitializerIdentity(
        labels=ownership,
        image=image,
        runtime_worker=spec.container_name if supervised else None,
        network_policy=attestation,
    )
    fingerprint = hashlib.sha256(
        canonical(identity.model_dump(mode="json", by_alias=True, exclude_none=True))
    ).hexdigest()
    environment = [
        "BRIAREUS_NODE_UUID=" + str(spec.node_uuid),
        "BRIAREUS_PROJECT_UUID=" + str(spec.project_uuid),
        "BRIAREUS_WORKSPACE_UUID=" + str(selected.id),
    ]
    host = ContainerHost(
        network_mode="none",
        memory=64 * 1024**2,
        memory_swap=64 * 1024**2,
        nano_cpus=1_000_000_000,
        pids=32,
        cap_add=["CHOWN"],
        mounts=[
            VolumeMount(source=volume_name(spec, selected), target="/workspace", read_only=False)
        ],
        log=LogConfiguration(options={"max-size": "1m", "max-file": "1"}),
    )
    if supervised:
        environment.append("BRIAREUS_RUNTIME_WORKER=" + spec.container_name)
        host.binds = [f"/var/lib/briareus/nodes/{spec.node_uuid}/gateway:/node-link:rw"]
    if attestation is not None:
        if not supervised:
            raise ValueError("Network attestation requires a private supervisor link")
        environment.append(
            "BRIAREUS_NETWORK_POLICY_ATTESTATION=" + attestation.canonical_bytes().decode()
        )
    return ContainerConfiguration(
        image=image,
        user="0:0",
        command=["/app/.venv/bin/python", "-m", "node_agent.workspace_init"],
        environment=environment,
        labels={
            **ownership.model_dump(by_alias=True),
            ROLE: "workspace-initializer",
            CONFIG: fingerprint,
        },
        host=host,
    )


async def ensure_volume(
    engine: WorkspaceEngine, spec: Deployment, workspace: WorkspaceMount
) -> None:
    name = volume_name(spec, workspace)
    expected = workspace_labels(spec, workspace).model_dump(by_alias=True)
    response = await engine.request("GET", f"/volumes/{name}", accepted=(200, 404))
    if response.status_code == 404:
        await engine.request(
            "POST",
            "/volumes/create",
            accepted=(201,),
            payload=VolumeCreate(name=name, driver="local", labels=expected),
        )
        response = await engine.request("GET", f"/volumes/{name}")
    volume = VolumeInspection.model_validate(response.json())
    if (
        volume.name != name
        or volume.driver != "local"
        or volume.options not in (None, {})
        or any(volume.labels.get(key) != value for key, value in expected.items())
    ):
        raise EngineFailure("Refusing foreign or host-backed workspace volume")


async def prepare_helper(engine: WorkspaceEngine, name: str, config: ContainerConfiguration) -> str:
    response = await engine.request(
        "GET", "/containers/json", params={"all": "true", "filters": json.dumps({"name": [name]})}
    )
    rows = TypeAdapter(list[ContainerSummary]).validate_python(response.json())
    exact = [row for row in rows if "/" + name in row.names]
    if len(exact) > 1 or any(not helper_labels_match(row.labels, config.labels) for row in exact):
        raise EngineFailure("Conflicting workspace initializer; explicit recovery required")
    if exact:
        return exact[0].identity
    created = await engine.request(
        "POST",
        "/containers/create",
        accepted=(201,),
        params={"name": name},
        payload=config,
    )
    return ContainerCreated.model_validate(created.json()).identity


async def run_helper(engine: WorkspaceEngine, container: str) -> None:
    try:
        async with asyncio.timeout(15):
            current = await engine.inspect(container)
            if current is not None and current.state.status == "created":
                await engine.request("POST", f"/containers/{container}/start", accepted=(204, 304))
            response = await engine.request(
                "POST", f"/containers/{container}/wait", params={"condition": "not-running"}
            )
            result = ContainerExit.model_validate(response.json())
            if result.status != 0 or result.error:
                failed = await engine.inspect(container)
                raise EngineFailure(
                    "Workspace initialization refused",
                    diagnostic=state_diagnostic(
                        "creating",
                        failed.state if failed else InspectedState(),
                        component="engine",
                    ),
                )
    except TimeoutError:
        raise EngineFailure("Workspace initializer exceeded its deadline") from None


async def cleanup_helper(
    engine: WorkspaceEngine, container: str, expected: Mapping[str, str]
) -> None:
    try:
        async with asyncio.timeout(5):
            current = await engine.inspect(container)
            if current is None:
                return
            if not helper_labels_match(current.config.labels, expected):
                raise EngineFailure("Workspace helper identity changed")
            if current.state.running:
                await engine.request(
                    "POST",
                    f"/containers/{container}/stop",
                    params={"t": 1},
                    accepted=(204, 304, 404),
                )
            await engine.request("DELETE", f"/containers/{container}", accepted=(204, 404))
    except (TimeoutError, EngineFailure):
        engine.workspace_cleanup_uncertain = True
        raise EngineFailure("Workspace helper cleanup is unresolved") from None


class DockerWorkspaces(_DeploymentBinding[WorkspaceEngine]):
    async def prepare(self, identity: WorkspaceIdentity) -> None:
        engine, spec = self.engine, self.spec
        if engine.workspace_cleanup_uncertain:
            raise EngineFailure("Workspace helper cleanup is unresolved")
        if engine.utility_image is None:
            raise EngineFailure("Approved initializer image is not configured")
        binding = next(
            mount
            for mount in (spec.workspace, spec.project_workspace)
            if mount is not None and workspace_identity(spec, mount) == identity
        )
        await ensure_volume(engine, spec, binding)
        config = initializer_config(
            spec,
            engine.utility_image,
            engine.network_attestations.get(spec.container_name),
            workspace=binding,
        )
        container = await prepare_helper(
            engine, "briareus-workspace-init-" + binding.id.hex, config
        )
        try:
            await run_helper(engine, container)
        finally:
            # Only the owned one-shot helper is stopped; project volumes remain.
            await cleanup_helper(engine, container, config.labels)


async def prepare_workspace(engine: WorkspaceEngine, spec: Deployment) -> None:
    identities = tuple(
        workspace_identity(spec, mount)
        for mount in (spec.workspace, spec.project_workspace)
        if mount is not None
    )
    await PrepareWorkspaces(DockerWorkspaces(engine, spec)).execute(identities)


async def recover_workspace_helpers(engine: WorkspaceEngine, node_uuid: UUID) -> None:
    response = await engine.request(
        "GET",
        "/containers/json",
        params={
            "all": "true",
            "filters": json.dumps(
                {"label": [f"{NODE_LABEL}={node_uuid}", f"{ROLE}=workspace-initializer"]}
            ),
        },
    )
    for row in TypeAdapter(list[ContainerSummary]).validate_python(response.json()):
        actual = row.labels
        try:
            workspace, project = UUID(actual[WORKSPACE_LABEL]), UUID(actual[PROJECT_LABEL])
            if (
                workspace.version != 4
                or project.version != 4
                or actual.get(NODE_LABEL) != str(node_uuid)
                or actual.get(ROLE) != "workspace-initializer"
                or "/briareus-workspace-init-" + workspace.hex not in row.names
            ):
                raise ValueError("Unverified initializer")
        except (ValueError, KeyError):
            raise EngineFailure("Refusing to reap an unverified workspace helper") from None
        current = await engine.inspect(row.identity)
        if current is None or current.config.labels != actual:
            raise EngineFailure("Workspace helper changed during recovery")
        # Preserve exact label equality on recovered helpers, plus fresh recheck.
        await cleanup_helper(engine, row.identity, actual)
    engine.workspace_cleanup_uncertain = False
