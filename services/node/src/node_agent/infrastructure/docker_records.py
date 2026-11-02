"""Common typed native observation port for lifecycle adapters."""

from typing import Protocol
from uuid import UUID

from .container_models import ContainerInspection, ContainerSummary


class ContainerObservationPort(Protocol):
    async def inspect(self, container_id: str) -> ContainerInspection | None: ...


class ContainerInventoryPort(ContainerObservationPort, Protocol):
    async def containers(self, node_uuid: UUID) -> tuple[ContainerSummary, ...]: ...
