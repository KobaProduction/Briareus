"""Resources-owned SQL projection of placements, receipts and effective runtime policy."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from node_protocol.diagnostics import FailureDiagnostic
from projects._catalog_ledger import OwnerAuditRow
from projects._node_persistence import NodeModuleRow, NodeOperationRow
from projects.application.placement_listing import PlacementOperationView, PlacementView
from projects.infrastructure.audit_records import PlacementAudit
from projects.infrastructure.runtime_settings import resolved_configuration
from projects.placement_recovery import current_spec
from service_runtime.platform_db_mechanics import _DatabaseBinding


def operation_view(
    row: NodeOperationRow, diagnostic: FailureDiagnostic | None
) -> PlacementOperationView:
    return PlacementOperationView(
        id=str(row.id),
        placement_uuid=str(row.placement_uuid),
        sequence=row.sequence,
        phase=row.phase,
        error=row.error_code,
        updated_at=row.updated_at.isoformat(),
        diagnostic=diagnostic,
    )


async def operation_diagnostic(tx: AsyncSession, row: NodeOperationRow) -> FailureDiagnostic | None:
    # Audit facts are bounded and scoped to this exact operation, placement and actor.
    records = await tx.scalars(
        select(OwnerAuditRow)
        .where(
            OwnerAuditRow.operation_uuid == row.id,
            OwnerAuditRow.object_id == str(row.placement_uuid),
            OwnerAuditRow.actor_user_id == row.actor_uuid,
            OwnerAuditRow.action.like("node.module.%"),
        )
        .order_by(OwnerAuditRow.created_at.desc())
        .limit(32)
    )
    for record in records:
        if isinstance(record.details, PlacementAudit) and record.details.diagnostic is not None:
            return record.details.diagnostic
    return None


class SqlPlacementReader(_DatabaseBinding[PlatformDatabase]):
    async def read(self, project_uuid: UUID, node_uuid: UUID | None) -> tuple[PlacementView, ...]:
        async with self.database.transaction() as tx:
            query = select(NodeModuleRow).where(NodeModuleRow.project_uuid == project_uuid)
            if node_uuid is not None:
                query = query.where(NodeModuleRow.node_uuid == node_uuid)
            placements = await tx.scalars(
                query.order_by(NodeModuleRow.name, NodeModuleRow.id).limit(100)
            )
            result = [await self._view(tx, item) for item in placements]
            return tuple(result)

    @staticmethod
    async def _view(tx: AsyncSession, item: NodeModuleRow) -> PlacementView:
        operation = await tx.scalar(
            select(NodeOperationRow)
            .where(NodeOperationRow.placement_uuid == item.id)
            .order_by(NodeOperationRow.sequence.desc())
            .limit(1)
        )
        summary = (
            operation_view(operation, await operation_diagnostic(tx, operation))
            if operation is not None
            else None
        )
        spec = current_spec(item, operation) if operation is not None else None
        configuration = spec.configuration if spec is not None else None
        desired_configuration = await resolved_configuration(tx, item.node_uuid, configuration)
        return PlacementView(
            id=str(item.id),
            node_uuid=str(item.node_uuid),
            project_uuid=str(item.project_uuid),
            name=item.name,
            module=item.artifact_key,
            state=item.state,
            sequence=item.sequence,
            limits=item.limits,
            workspace_uuid=str(item.storage_uuid) if item.storage_uuid else None,
            release_uuid=str(
                item.applied_release_uuid if item.state == "ready" else item.desired_release_uuid
            ),
            configuration=configuration,
            project_workspace=spec.project_workspace if spec is not None else None,
            operation=summary,
            runtime_policy_pending=spec is not None and desired_configuration != configuration,
        )
