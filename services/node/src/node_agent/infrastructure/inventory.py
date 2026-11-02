"""Decode native inspection data before it can affect placement capacity."""

import re
from typing import Literal
from uuid import UUID

from pydantic import ValidationError

from node_agent.docker_engine import DEPLOYMENT_LABEL, SPEC_LABEL
from node_agent.domain.inventory import Allocation, InventoryInvalid, ManagedComponent
from node_agent.runtime_profiles import (
    EGRESS_CPU,
    EGRESS_MEMORY,
    EGRESS_PIDS,
    EGRESS_REQUIRED,
    ROLE_LABEL,
)
from node_protocol import ResourceLimits

from .container_models import ContainerInspection
from .docker_records import ContainerInventoryPort
from .runtime_bindings import _EngineBinding


def egress_quota() -> Allocation:
    return Allocation(EGRESS_MEMORY, EGRESS_CPU, EGRESS_PIDS)


def component_role(
    inspection: ContainerInspection, allocation: Allocation
) -> Literal["main", "egress"]:
    role = inspection.config.labels.get(ROLE_LABEL)
    if role is None:
        return "main"
    if role != "egress":
        raise InventoryInvalid("Unknown execution component")
    host = inspection.host
    if (
        allocation != egress_quota()
        or host.binds
        or host.mounts
        or host.privileged
        or not host.read_only
        or inspection.config.user != "1000:1000"
    ):
        raise InventoryInvalid("Unverified isolated egress budget")
    return "egress"


def component(inspection: ContainerInspection) -> ManagedComponent:
    metadata = inspection.config.labels
    placement = UUID(metadata[DEPLOYMENT_LABEL])
    fingerprint = metadata[SPEC_LABEL]
    if placement.version != 4 or not re.fullmatch(r"[a-f0-9]{64}", fingerprint):
        raise InventoryInvalid("Invalid managed instance")
    memory, nano_cpus, pids = (
        inspection.host.memory,
        inspection.host.nano_cpus,
        inspection.host.pids,
    )
    if memory is None or nano_cpus is None or pids is None:
        raise InventoryInvalid("Managed instance has unverified resource configuration")
    quota = ResourceLimits(memory_bytes=memory, cpu_millis=nano_cpus // 1_000_000, pids=pids)
    allocation = Allocation(quota.memory_bytes, quota.cpu_millis, quota.pids)
    return ManagedComponent(
        inspection.identity,
        inspection.name.removeprefix("/"),
        placement,
        fingerprint,
        allocation,
        component_role(inspection, allocation),
        inspection.state.running is True,
        inspection.state.health is not None and inspection.state.health.status == "healthy",
        metadata.get(EGRESS_REQUIRED) == "true",
    )


class DockerComponentInventory(_EngineBinding[ContainerInventoryPort]):
    async def read(self, node_uuid: UUID) -> tuple[ManagedComponent, ...]:
        try:
            summaries = await self._engine.containers(node_uuid)
            result = []
            for summary in summaries:
                current = await self._engine.inspect(summary.identity)
                if current is not None:
                    result.append(component(current))
            return tuple(result)
        except (ValidationError, ValueError, KeyError, TypeError) as exc:
            raise InventoryInvalid(
                "Managed instance has unverified resource configuration"
            ) from exc
