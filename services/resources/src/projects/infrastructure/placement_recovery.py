"""Resources SQL adapter for atomic recovery of an approved retained deployment."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from node_protocol import Deployment
from projects._catalog_ledger import OwnerAuditRow, OwnerCommandRow
from projects._node_persistence import (
    ModuleArtifactRow,
    ModuleReleaseRow,
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    NodeStorageRow,
)
from projects.application.placement_recovery import PlacementRecoverySession
from projects.domain.node_administration import NodeActor, NodeConflict
from projects.domain.placement_recovery import RecoveryIntent, RecoveryReplay
from projects.infrastructure.audit_records import PlacementAudit
from projects.infrastructure.placement_audit import audit_placement
from projects.infrastructure.placement_mutations import SqlPlacementMutationSession
from projects.infrastructure.placement_nodes import qualified_placement_node
from projects.infrastructure.placement_releases import approved_placement_release
from projects.infrastructure.placement_storage import require_project_workspace
from projects.infrastructure.placement_update import current_update_storage
from projects.placement_recovery import current_spec
from service_runtime.platform_db_mechanics import _DatabaseBinding


@dataclass(frozen=True)
class AppliedRecovery:
    deployment: Deployment
    release_uuid: UUID
    storage_uuid: UUID


async def applied_recovery(
    tx: AsyncSession, placement: NodeModuleRow, previous: NodeOperationRow
) -> AppliedRecovery:
    spec = current_spec(placement, previous)
    release = await tx.get(ModuleReleaseRow, placement.applied_release_uuid)
    artifact = await tx.get(ModuleArtifactRow, placement.artifact_key)
    if (
        release is None
        or release.state != "published"
        or artifact is None
        or not artifact.enabled
        or release.artifact_key != placement.artifact_key
        or release.image_reference != spec.release.image
        or spec.id != placement.id
        or spec.project_uuid != placement.project_uuid
        or spec.node_uuid != placement.node_uuid
        or spec.workspace is None
        or spec.workspace.id != placement.storage_uuid
    ):
        raise NodeConflict("Current approved applied deployment required")
    storage = await tx.get(NodeStorageRow, placement.storage_uuid)
    if (
        storage is None
        or storage.node_uuid != placement.node_uuid
        or storage.project_uuid != placement.project_uuid
        or storage.retention != "persistent"
    ):
        raise NodeConflict("Current project storage required")
    return AppliedRecovery(spec, release.id, storage.id)


async def recovery_node(tx: AsyncSession, node_uuid: UUID, actor: NodeActor) -> NodeRow:
    return qualified_placement_node(
        await tx.get(NodeRow, node_uuid), actor, scope_detail="Current node ownership required"
    )


class SqlPlacementRecoveryTransactions(_DatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PlacementRecoverySession]:
        async with self.database.transaction() as tx:
            yield SqlPlacementRecoverySession(tx)


class SqlPlacementRecoverySession(SqlPlacementMutationSession):
    async def receipt(self, operation_uuid: UUID) -> RecoveryReplay | None:
        row = await self.tx.get(NodeOperationRow, operation_uuid)
        if row is not None:
            return RecoveryReplay(
                row.actor_uuid, row.placement_uuid, row.sequence, row.previous == row.desired
            )
        receipt = await self.tx.scalar(
            select(OwnerCommandRow).where(
                OwnerCommandRow.operation_uuid == operation_uuid,
                OwnerCommandRow.operation == "node.module.resume",
            )
        )
        return await self._resume_receipt(receipt) if receipt is not None else None

    async def _resume_receipt(self, receipt: OwnerCommandRow) -> RecoveryReplay:
        try:
            nonce, target = receipt.key.split(":")
            if nonce != str(receipt.operation_uuid) or receipt.state != "completed":
                raise ValueError("Completed resume receipt required")
            operation = await self.tx.get(NodeOperationRow, UUID(target))
            if operation is None or str(operation.sequence) != receipt.expected_owner_revision:
                raise ValueError("Original resume operation required")
            return RecoveryReplay(
                UUID(receipt.actor_scope),
                operation.placement_uuid,
                operation.sequence,
                True,
                operation.id,
                receipt.fingerprint,
            )
        except ValueError:
            raise NodeConflict("Recovery resume receipt unavailable") from None

    async def resume(self, intent: RecoveryIntent, actor: NodeActor) -> UUID:
        placement, previous = self.placement, self.previous
        if placement is None or previous is None:
            raise ValueError("Resume requires the locked current operation")
        await recovery_node(self.tx, placement.node_uuid, actor)
        approved = await approved_placement_release(
            self.tx, placement.desired_release_uuid, module=placement.artifact_key
        )
        spec = previous.desired
        if previous.sequence != placement.sequence or spec.release != approved.spec:
            raise NodeConflict("Current approved placement intent required")
        storage_uuid = await current_update_storage(self.tx, placement, spec, approved.definition)
        await require_project_workspace(
            self.tx,
            spec.project_workspace,
            module=spec.release.module,
            node_uuid=placement.node_uuid,
            project_uuid=intent.project_uuid,
            private_storage_uuid=storage_uuid,
        )
        self.tx.add(
            OwnerCommandRow(
                operation_uuid=intent.operation_uuid,
                actor_scope=str(intent.actor_uuid),
                project_scope=str(intent.project_uuid),
                operation="node.module.resume",
                key=str(intent.operation_uuid) + ":" + str(previous.id),
                fingerprint=intent.fingerprint,
                expected_owner_revision=str(intent.expected_sequence),
                state="completed",
                expires_at=datetime.now(UTC) + timedelta(days=1),
            )
        )
        self.tx.add(
            OwnerAuditRow(
                operation_uuid=intent.operation_uuid,
                actor_user_id=intent.actor_uuid,
                project_id=intent.project_uuid,
                action="node.module.resume",
                object_id=str(placement.id),
                owner_revision=str(placement.sequence),
                details=PlacementAudit(node_uuid=placement.node_uuid, phase="resume_requested"),
            )
        )
        await self.tx.flush()
        return previous.id

    async def stage(self, intent: RecoveryIntent, actor: NodeActor) -> None:
        placement, previous = self.placement, self.previous
        if placement is None or previous is None:
            raise ValueError("Recovery must lock and qualify the current placement")
        if placement.id != intent.placement_uuid or placement.project_uuid != intent.project_uuid:
            raise ValueError("Recovery placement selectors changed")
        node = await recovery_node(self.tx, placement.node_uuid, actor)
        applied = await applied_recovery(self.tx, placement, previous)
        spec = applied.deployment
        await require_project_workspace(
            self.tx,
            spec.project_workspace,
            module=spec.release.module,
            node_uuid=node.id,
            project_uuid=intent.project_uuid,
            private_storage_uuid=applied.storage_uuid,
        )
        placement.sequence += 1
        placement.state = "updating"
        placement.desired_release_uuid = applied.release_uuid
        operation = NodeOperationRow(
            id=intent.operation_uuid,
            node_uuid=node.id,
            placement_uuid=placement.id,
            actor_uuid=intent.actor_uuid,
            sequence=placement.sequence,
            fingerprint=spec.fingerprint,
            desired=spec,
            previous=spec,
            phase="queued",
        )
        self.tx.add(operation)
        await self.tx.flush()
        audit_placement(self.tx, operation, placement, "queued")
