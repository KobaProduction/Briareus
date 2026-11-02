"""Single-instance reconciliation; target sessions may stop during replacement.

The planner never authorizes effects or assumes that a missing session count
means zero. Runtime reports are observations, not permission grants.
"""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from node_protocol import Deployment, NodeRecord, ResourceLimits

from .domain.inventory import Allocation, ObservedPlacement
from .domain.planning import (
    Capacity,
    PlanAction,
    PlanningNode,
    PlanningTarget,
    replacement_plan,
)


@dataclass(frozen=True)
class Instance:
    container_id: str
    deployment_uuid: UUID
    fingerprint: str
    limits: ResourceLimits
    running: bool
    ready: bool


@dataclass(frozen=True)
class Plan:
    action: PlanAction
    reason: str
    deployment: Deployment


def plan(node: NodeRecord, desired: Deployment, observed: list[Instance]) -> Plan:
    decision = replacement_plan(
        planning_node(node), planning_target(desired), observations(observed)
    )
    return Plan(decision.action, decision.reason, desired)


def allocation(limits: ResourceLimits) -> Allocation:
    return Allocation(limits.memory_bytes, limits.cpu_millis, limits.pids)


def planning_node(node: NodeRecord) -> PlanningNode:
    return PlanningNode(
        node.id,
        node.enabled,
        Capacity(allocation(node.budget.total), allocation(node.budget.reserved)),
    )


def planning_target(desired: Deployment) -> PlanningTarget:
    return PlanningTarget(
        desired.id,
        desired.node_uuid,
        desired.enabled,
        desired.fingerprint,
        allocation(desired.limits),
    )


def observations(observed: list[Instance]) -> tuple[ObservedPlacement, ...]:
    return tuple(
        ObservedPlacement(
            item.container_id,
            item.deployment_uuid,
            item.fingerprint,
            allocation(item.limits),
            item.running,
            item.ready,
        )
        for item in observed
    )
