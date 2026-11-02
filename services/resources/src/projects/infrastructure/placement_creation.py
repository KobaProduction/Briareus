"""Persist a new placement, project route, queued operation and audit as one intent."""

from sqlalchemy.ext.asyncio import AsyncSession

from projects._node_persistence import NodeModuleRow, NodeOperationRow, ProjectModuleBindingRow
from projects.application.placement_execution import PlacementCreationIntent
from projects.application.placement_listing import PlacementOperationView
from projects.domain.placement_admission import placement_name
from projects.infrastructure.node_storage_models import PlacementCreationMetadata
from projects.infrastructure.placement_audit import audit_placement
from projects.infrastructure.placement_listing import operation_view


async def create_placement_intent(
    tx: AsyncSession, intent: PlacementCreationIntent
) -> PlacementOperationView:
    spec = intent.deployment
    if spec.workspace is None:
        raise ValueError("New placement requires private project storage")
    placement = NodeModuleRow(
        id=spec.id,
        node_uuid=spec.node_uuid,
        project_uuid=spec.project_uuid,
        artifact_key=spec.release.module,
        name=placement_name(intent.name),
        desired_release_uuid=intent.release_uuid,
        storage_uuid=spec.workspace.id,
        limits=spec.limits,
        configuration=PlacementCreationMetadata(intent_digest=intent.intent_digest),
        sequence=1,
        state="pending",
    )
    tx.add(placement)
    await tx.flush()
    tx.add(
        ProjectModuleBindingRow(
            project_uuid=spec.project_uuid,
            placement_uuid=placement.id,
            logical_key=spec.release.module,
        )
    )
    operation = NodeOperationRow(
        id=intent.operation_uuid,
        node_uuid=spec.node_uuid,
        placement_uuid=placement.id,
        actor_uuid=intent.actor_uuid,
        sequence=1,
        fingerprint=spec.fingerprint,
        desired=spec,
        phase="queued",
    )
    tx.add(operation)
    await tx.flush()
    audit_placement(tx, operation, placement, "queued")
    return operation_view(operation, None)
