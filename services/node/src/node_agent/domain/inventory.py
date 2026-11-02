"""Complete placements account for missing and orphaned execution components."""

import re
from dataclasses import dataclass
from typing import Literal
from uuid import UUID


class InventoryInvalid(ValueError):
    """Observed components cannot be safely used for admission accounting."""


@dataclass(frozen=True, slots=True)
class Allocation:
    memory_bytes: int
    cpu_millis: int
    pids: int

    def plus(self, other: "Allocation") -> "Allocation":
        return Allocation(
            self.memory_bytes + other.memory_bytes,
            self.cpu_millis + other.cpu_millis,
            self.pids + other.pids,
        )


@dataclass(frozen=True, slots=True)
class ManagedComponent:
    container_id: str
    name: str
    deployment_uuid: UUID
    fingerprint: str
    allocation: Allocation
    role: Literal["main", "egress"]
    running: bool
    ready: bool
    requires_egress: bool = False


@dataclass(frozen=True, slots=True)
class ObservedPlacement:
    container_id: str
    deployment_uuid: UUID
    fingerprint: str
    allocation: Allocation
    running: bool
    ready: bool


def egress_name(container_name: str) -> str:
    if not re.fullmatch(r"briareus-[a-f0-9]{48}", container_name):
        raise InventoryInvalid("Derived placement name required")
    return container_name + "-egress"


def complete_placement(
    main: ManagedComponent, helper: ManagedComponent | None, missing_quota: Allocation
) -> ObservedPlacement:
    allocation, running, ready = main.allocation, main.running, main.ready
    if main.requires_egress:
        allocation = allocation.plus(helper.allocation if helper else missing_quota)
        running = running and helper is not None and helper.running
        ready = ready and helper is not None and helper.ready
    if helper and (
        helper.deployment_uuid != main.deployment_uuid or helper.fingerprint != main.fingerprint
    ):
        raise InventoryInvalid("Egress component belongs to a different placement revision")
    return ObservedPlacement(
        main.container_id, main.deployment_uuid, main.fingerprint, allocation, running, ready
    )


def placement_inventory(
    components: tuple[ManagedComponent, ...], missing_quota: Allocation
) -> tuple[ObservedPlacement, ...]:
    mains: list[ManagedComponent] = []
    helpers: dict[str, ManagedComponent] = {}
    for component in components:
        if component.role == "main":
            mains.append(component)
        elif component.name in helpers:
            raise InventoryInvalid("Duplicate placement egress")
        else:
            helpers[component.name] = component
    result = []
    for main in mains:
        helper = helpers.pop(egress_name(main.name), None) if main.requires_egress else None
        result.append(complete_placement(main, helper, missing_quota))
    # An interrupted create must remain counted and blocked, never adopted as
    # a healthy complete module merely because its labels look familiar.
    result.extend(
        ObservedPlacement(
            item.container_id, item.deployment_uuid, item.fingerprint, item.allocation, False, False
        )
        for item in helpers.values()
    )
    return tuple(result)
