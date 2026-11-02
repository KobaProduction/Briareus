"""Explicit recovery preserves committed intent and durable command identity."""

import hashlib
from dataclasses import dataclass
from uuid import UUID

from projects.domain.node_administration import NodeConflict


class PlacementReconciliationBusy(ValueError):
    pass


@dataclass(frozen=True)
class RecoveryIntent:
    operation_uuid: UUID
    actor_uuid: UUID
    project_uuid: UUID
    placement_uuid: UUID
    expected_sequence: int

    @property
    def fingerprint(self) -> str:
        selectors = (
            self.operation_uuid,
            self.actor_uuid,
            self.project_uuid,
            self.placement_uuid,
            self.expected_sequence,
        )
        return hashlib.sha256(":".join(str(value) for value in selectors).encode()).hexdigest()


@dataclass(frozen=True)
class RecoveryReplay:
    actor_uuid: UUID
    placement_uuid: UUID
    sequence: int
    unchanged_deployment: bool
    resumed_operation: UUID | None = None
    fingerprint: str | None = None

    def require_matches(self, intent: RecoveryIntent) -> None:
        sequence = intent.expected_sequence + (self.resumed_operation is None)
        if (
            self.actor_uuid != intent.actor_uuid
            or self.placement_uuid != intent.placement_uuid
            or self.sequence != sequence
            or not self.unchanged_deployment
            or (self.resumed_operation is not None and self.fingerprint != intent.fingerprint)
        ):
            raise NodeConflict("Recovery operation identity conflicts")


def require_reconciliation_capacity(active: int) -> None:
    if active >= 16:
        raise PlacementReconciliationBusy("Node operation reconciliation is busy")
