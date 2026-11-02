"""Persist placement audit facts in the same owner transaction as the operation."""

from sqlalchemy.ext.asyncio import AsyncSession

from node_protocol import Deployment
from node_protocol.diagnostics import FailureDiagnostic
from projects._catalog_ledger import OwnerAuditRow
from projects._node_persistence import NodeModuleRow, NodeOperationRow
from projects.infrastructure.audit_records import PlacementAudit


def audit_placement(
    tx: AsyncSession,
    operation: NodeOperationRow,
    placement: NodeModuleRow,
    phase: str,
    diagnostic: FailureDiagnostic | None = None,
    restored: Deployment | None = None,
) -> None:
    tx.add(
        OwnerAuditRow(
            operation_uuid=operation.id,
            actor_user_id=operation.actor_uuid,
            project_id=placement.project_uuid,
            action="node.module." + phase,
            object_id=str(placement.id),
            owner_revision=str(operation.sequence),
            details=PlacementAudit(
                node_uuid=operation.node_uuid,
                phase=phase,
                diagnostic=diagnostic,
                restored_fingerprint=restored.fingerprint if restored is not None else None,
            ),
        )
    )
