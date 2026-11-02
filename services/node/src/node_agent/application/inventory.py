"""Refresh native components before computing complete placement allocations."""

from typing import Protocol
from uuid import UUID

from node_agent.domain.inventory import (
    Allocation,
    ManagedComponent,
    ObservedPlacement,
    placement_inventory,
)


class ComponentInventoryPort(Protocol):
    async def read(self, node_uuid: UUID) -> tuple[ManagedComponent, ...]: ...


class ObserveInventory:
    def __init__(self, components: ComponentInventoryPort, missing_quota: Allocation) -> None:
        self._components = components
        self._missing_quota = missing_quota

    async def execute(self, node_uuid: UUID) -> tuple[ObservedPlacement, ...]:
        components = await self._components.read(node_uuid)
        return placement_inventory(components, self._missing_quota)
