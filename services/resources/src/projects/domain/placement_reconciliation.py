"""Receipt monotonicity and the evidence needed to restore a prior placement."""

from dataclasses import dataclass
from uuid import UUID

ACTIVE_PHASES = frozenset({"queued", "pulling", "stopping", "creating", "checking", "rolling_back"})
TERMINAL_PHASES = frozenset({"succeeded", "failed"})
RECEIPT_ERRORS = frozenset(
    {"UPDATE_FAILED", "ROLLBACK_FAILED", "CONTROLLER_INTERRUPTED", "UNMANAGED_INSTANCE", None}
)


@dataclass(frozen=True)
class OperationState:
    operation_uuid: UUID
    sequence: int
    phase: str
    error: str | None


@dataclass(frozen=True)
class OperationReceipt:
    operation_uuid: UUID
    sequence: int
    phase: str
    error: str | None

    def validate_for(self, operation: OperationState, placement_sequence: int) -> None:
        if (
            self.operation_uuid != operation.operation_uuid
            or self.sequence != operation.sequence
            or self.phase not in ACTIVE_PHASES | TERMINAL_PHASES
            or self.error not in RECEIPT_ERRORS
        ):
            raise ValueError("Signed operation selectors mismatch")
        if placement_sequence != operation.sequence:
            raise ValueError("Operation no longer current")
        if operation.phase in TERMINAL_PHASES and (self.phase, self.error) != (
            operation.phase,
            operation.error,
        ):
            raise ValueError("Terminal operation receipt changed")


@dataclass(frozen=True)
class PlacementIdentity:
    placement_uuid: UUID
    node_uuid: UUID
    project_uuid: UUID
    module: str
    storage_uuid: UUID | None


@dataclass(frozen=True)
class RetainedDeployment:
    identity: PlacementIdentity
    enabled: bool
    fingerprint: str

    def belongs_to(self, placement: PlacementIdentity, operation_node: UUID) -> bool:
        return (
            self.enabled
            and self.identity == placement
            and self.identity.storage_uuid is not None
            and self.identity.node_uuid == operation_node
        )


@dataclass(frozen=True)
class NodeObservation:
    node_uuid: UUID
    sequence: int
    enabled: bool
    deleted: bool


@dataclass(frozen=True)
class RuntimeRestoration:
    node_uuid: UUID | None
    sequence: int | None
    enabled: bool
    matching_count: int
    running: bool
    ready: bool
    fingerprint: str | None
    limits_match: bool

    def confirms(self, node: NodeObservation, previous: RetainedDeployment) -> bool:
        return (
            node.enabled
            and not node.deleted
            and self.enabled
            and self.node_uuid == node.node_uuid
            and self.sequence == node.sequence
            and self.matching_count == 1
            and self.running
            and self.ready
            and self.fingerprint == previous.fingerprint
            and self.limits_match
        )


def restoration_allowed(
    placement: PlacementIdentity,
    operation_node: UUID,
    previous: RetainedDeployment,
    node: NodeObservation,
    inventory: RuntimeRestoration,
) -> bool:
    return (
        node.node_uuid == operation_node
        and previous.belongs_to(placement, operation_node)
        and inventory.confirms(node, previous)
    )


def restored_spec_required(state: str, phase: str, error: str | None, has_previous: bool) -> bool:
    return state == "ready" and phase == "failed" and error == "UPDATE_FAILED" and has_previous
