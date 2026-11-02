"""Target-only replacement decisions from complete, explicitly budgeted observations."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from .inventory import Allocation, ObservedPlacement

PlanAction = Literal["keep", "create", "replace", "blocked", "disabled"]


@dataclass(frozen=True, slots=True)
class Capacity:
    total: Allocation
    reserved: Allocation

    def fits(self, allocations: tuple[Allocation, ...]) -> bool:
        used = self.reserved
        for allocation in allocations:
            used = used.plus(allocation)
        return (
            used.memory_bytes <= self.total.memory_bytes
            and used.cpu_millis <= self.total.cpu_millis
            and used.pids <= self.total.pids
        )


@dataclass(frozen=True, slots=True)
class PlanningNode:
    node_uuid: UUID
    enabled: bool
    capacity: Capacity


@dataclass(frozen=True, slots=True)
class PlanningTarget:
    placement_uuid: UUID
    node_uuid: UUID
    enabled: bool
    fingerprint: str
    allocation: Allocation


@dataclass(frozen=True, slots=True)
class PlanDecision:
    action: PlanAction
    reason: str


def replacement_plan(
    node: PlanningNode, target: PlanningTarget, observed: tuple[ObservedPlacement, ...]
) -> PlanDecision:
    if target.node_uuid != node.node_uuid:
        raise ValueError("Deployment belongs to another node")
    if not node.enabled or not target.enabled:
        return PlanDecision("disabled", "Admission disabled; existing processes retained")
    own = tuple(item for item in observed if item.deployment_uuid == target.placement_uuid)
    if len(own) > 1:
        return PlanDecision("blocked", "Ambiguous placement instances; explicit recovery required")
    if own and own[0].fingerprint == target.fingerprint:
        if own[0].running and own[0].ready:
            return PlanDecision("keep", "Desired instance is ready")
        return PlanDecision("blocked", "Existing candidate needs inspection; no automatic restart")
    allocations = tuple(item.allocation for item in observed if item not in own)
    if not node.capacity.fits((*allocations, target.allocation)):
        return PlanDecision("blocked", "Insufficient capacity after target replacement")
    return PlanDecision("replace" if own else "create", "Only the target placement may stop")


def completion_matches(
    target: PlanningTarget,
    container: str | None,
    observed: tuple[ObservedPlacement, ...],
    node: PlanningNode,
) -> bool:
    if not node.enabled or not target.enabled or node.node_uuid != target.node_uuid:
        return False
    own = tuple(item for item in observed if item.deployment_uuid == target.placement_uuid)
    if len(own) != 1:
        return False
    candidate = own[0]
    return (
        candidate.container_id == container
        and candidate.fingerprint == target.fingerprint
        and candidate.allocation == target.allocation
        and candidate.running
        and candidate.ready
        and node.capacity.fits(tuple(item.allocation for item in observed))
    )
