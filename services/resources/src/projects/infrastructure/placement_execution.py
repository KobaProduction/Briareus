"""Read a placement execution target without retaining SQL locks during peer I/O."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from node_protocol import Deployment
from node_protocol.domain.observations import NodeReply
from projects._node_persistence import ModuleReleaseRow, NodeModuleRow, NodeOperationRow, NodeRow
from projects.application.placement_execution import PlacementExecutionTarget
from projects.placement_recovery import verified_restoration


async def execution_target(
    tx: AsyncSession, operation_uuid: UUID, project_uuid: UUID
) -> PlacementExecutionTarget | None:
    operation = await tx.get(NodeOperationRow, operation_uuid)
    if operation is None:
        raise ValueError("Operation disappeared")
    placement = await tx.get(NodeModuleRow, operation.placement_uuid)
    node = await tx.get(NodeRow, operation.node_uuid)
    if (
        placement is None
        or node is None
        or placement.project_uuid != project_uuid
        or node.deleted_at is not None
        or not node.enabled
        or not node.public_key
    ):
        raise ValueError("Current enabled project node required")
    if operation.phase == "succeeded" or (
        operation.phase == "failed" and operation.error_code != "UPDATE_FAILED"
    ):
        return None
    return PlacementExecutionTarget(
        node.endpoint,
        node.public_key,
        operation.sequence,
        operation.desired,
    )


async def approved_restoration(
    tx: AsyncSession,
    placement: NodeModuleRow,
    operation: NodeOperationRow,
    payload: NodeReply,
    inventory: NodeReply | None,
) -> Deployment | None:
    node = await tx.get(NodeRow, operation.node_uuid) if inventory is not None else None
    restored = verified_restoration(placement, operation, payload, inventory, node=node)
    if restored is None:
        return None
    release = await tx.get(ModuleReleaseRow, placement.applied_release_uuid)
    if (
        release is None
        or release.image_reference != restored.release.image
        or release.artifact_key != placement.artifact_key
    ):
        return None
    return restored
