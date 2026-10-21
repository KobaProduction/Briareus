"""Single-instance reconciliation; target sessions may stop during replacement.

The planner never authorizes effects or assumes that a missing session count
means zero. Runtime reports are observations, not permission grants.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from node_protocol import Deployment, NodeRecord, ResourceLimits


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
    action: Literal["keep", "create", "replace", "blocked", "disabled"]
    reason: str
    deployment: Deployment


def plan(node: NodeRecord, desired: Deployment, observed: list[Instance]) -> Plan:
    if desired.node_uuid != node.id:
        raise ValueError("Deployment belongs to another node")
    if not node.enabled or not desired.enabled:
        # Disabling admission does not terminate processes implicitly.
        return Plan("disabled", "Admission disabled; existing processes retained", desired)
    own = [item for item in observed if item.deployment_uuid == desired.id]
    if len(own) > 1:
        return Plan("blocked", "Ambiguous placement instances; explicit recovery required", desired)
    matching = [item for item in own if item.fingerprint == desired.fingerprint]
    if matching:
        if len(matching) == 1 and matching[0].running and matching[0].ready:
            return Plan("keep", "Desired instance is ready", desired)
        return Plan("blocked", "Existing candidate needs inspection; no automatic restart", desired)
    allocations = [item.limits for item in observed if item.deployment_uuid != desired.id]
    if not node.budget.fits([*allocations, desired.limits]):
        return Plan("blocked", "Insufficient capacity after target replacement", desired)
    return Plan("replace" if own else "create", "Only the target placement may stop", desired)
