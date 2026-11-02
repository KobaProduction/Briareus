"""Shared locked placement reads within one Resources mutation transaction."""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from projects._node_persistence import NodeModuleRow, NodeOperationRow
from projects.application.placement_listing import PlacementOperationView
from projects.domain.placement_admission import PlacementMutationState
from projects.infrastructure.placement_listing import operation_diagnostic, operation_view


class SqlPlacementMutationSession:
    def __init__(self, tx: AsyncSession) -> None:
        self.tx = tx
        self.placement: NodeModuleRow | None = None
        self.previous: NodeOperationRow | None = None

    async def lock(self, placement_uuid: UUID, project_uuid: UUID) -> PlacementMutationState | None:
        row = await self.tx.scalar(
            select(NodeModuleRow).where(NodeModuleRow.id == placement_uuid).with_for_update()
        )
        if row is None or row.project_uuid != project_uuid:
            return None
        self.placement = row
        return PlacementMutationState(row.id, row.node_uuid, row.sequence, row.state)

    async def latest_phase(self, placement_uuid: UUID) -> str | None:
        self.previous = await self.tx.scalar(
            select(NodeOperationRow)
            .where(NodeOperationRow.placement_uuid == placement_uuid)
            .order_by(NodeOperationRow.sequence.desc())
            .limit(1)
        )
        return self.previous.phase if self.previous is not None else None

    async def summary(self, operation_uuid: UUID) -> PlacementOperationView:
        row = await self.tx.get(NodeOperationRow, operation_uuid)
        if row is None:
            raise ValueError("Placement operation disappeared")
        return operation_view(row, await operation_diagnostic(self.tx, row))
