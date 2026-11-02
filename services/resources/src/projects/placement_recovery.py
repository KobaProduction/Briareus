"""Translate owner records and authenticated runtime evidence for restoration policy."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from node_protocol import Deployment
from node_protocol.domain.observations import (
    NodeInventory,
    NodeOperation,
    NodeReply,
    ObservedLimits,
    ObservedModule,
)
from projects.domain.placement_reconciliation import (
    NodeObservation,
    PlacementIdentity,
    RetainedDeployment,
    RuntimeRestoration,
    restoration_allowed,
    restored_spec_required,
)


class PlacementRecord(Protocol):
    id: UUID
    node_uuid: UUID
    project_uuid: UUID
    artifact_key: str
    storage_uuid: UUID | None
    state: str
    applied_release_uuid: UUID | None


class OperationRecord(Protocol):
    node_uuid: UUID
    phase: str
    error_code: str | None

    @property
    def previous(self) -> Deployment | None: ...

    @property
    def desired(self) -> Deployment: ...


class NodeRecord(Protocol):
    id: UUID
    sequence: int
    enabled: bool
    deleted_at: datetime | None


def current_spec(placement: PlacementRecord, operation: OperationRecord) -> Deployment:
    restored = restored_spec_required(
        placement.state, operation.phase, operation.error_code, operation.previous is not None
    )
    selected = operation.previous if restored else operation.desired
    if selected is None:
        raise ValueError("Retained deployment evidence required for restoration")
    return selected


def matching_deployments(
    items: tuple[ObservedModule, ...], placement_uuid: UUID
) -> tuple[ObservedModule, ...]:
    return tuple(item for item in items if item.placement_uuid == placement_uuid)


def runtime_evidence(inventory: NodeInventory, previous: Deployment) -> RuntimeRestoration:
    own = matching_deployments(inventory.items, previous.id)
    item = own[0] if len(own) == 1 else None
    expected = ObservedLimits(
        previous.limits.memory_bytes, previous.limits.cpu_millis, previous.limits.pids
    )
    return RuntimeRestoration(
        inventory.node_uuid,
        inventory.sequence,
        inventory.enabled,
        len(own),
        item is not None and item.running,
        item is not None and item.ready,
        item.fingerprint if item else None,
        item is not None and item.limits == expected,
    )


def verified_restoration(
    placement: PlacementRecord,
    operation: OperationRecord,
    receipt: NodeReply,
    inventory: NodeReply | None,
    *,
    node: NodeRecord | None,
) -> Deployment | None:
    if (
        not isinstance(receipt, NodeOperation)
        or receipt.phase != "failed"
        or receipt.error != "UPDATE_FAILED"
        or operation.previous is None
        or placement.applied_release_uuid is None
        or not isinstance(inventory, NodeInventory)
        or node is None
    ):
        return None
    if (
        inventory.enabled is not True
        or inventory.node_uuid != operation.node_uuid
        or node.id != operation.node_uuid
        or not node.enabled
        or node.deleted_at is not None
        or inventory.sequence != node.sequence
    ):
        return None
    previous = operation.previous
    identity = PlacementIdentity(
        placement.id,
        placement.node_uuid,
        placement.project_uuid,
        placement.artifact_key,
        placement.storage_uuid,
    )
    retained = RetainedDeployment(
        PlacementIdentity(
            previous.id,
            previous.node_uuid,
            previous.project_uuid,
            previous.release.module,
            previous.workspace.id if previous.workspace else None,
        ),
        previous.enabled,
        previous.fingerprint,
    )
    observed = NodeObservation(node.id, node.sequence, node.enabled, node.deleted_at is not None)
    if restoration_allowed(
        identity, operation.node_uuid, retained, observed, runtime_evidence(inventory, previous)
    ):
        return previous
    return None
