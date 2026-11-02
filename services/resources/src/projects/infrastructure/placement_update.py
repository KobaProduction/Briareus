"""Resources SQL adapter for exact update replay and atomic desired-state changes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from pydantic_core import MISSING
from sqlalchemy.ext.asyncio import AsyncSession

from common.platform_db import PlatformDatabase
from node_protocol import Deployment
from node_protocol.management import PlacementUpdate
from projects._node_persistence import (
    ModuleReleaseRow,
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    NodeStorageRow,
)
from projects.application.placement_update import PlacementUpdateSession, PreparedPlacementUpdate
from projects.domain.module_catalog import ArtifactDefinition
from projects.domain.node_administration import NodeActor, NodeConflict
from projects.domain.placement_update import UpdateIntent, UpdateReplay, UpdateReplayFields
from projects.infrastructure.placement_audit import audit_placement
from projects.infrastructure.placement_mutations import SqlPlacementMutationSession
from projects.infrastructure.placement_nodes import qualified_placement_node
from projects.infrastructure.placement_releases import approved_placement_release
from projects.infrastructure.placement_storage import require_project_workspace
from projects.infrastructure.runtime_settings import resolved_configuration
from projects.placement_recovery import current_spec
from service_runtime.platform_db_mechanics import _DatabaseBinding


async def current_update_storage(
    tx: AsyncSession, placement: NodeModuleRow, spec: Deployment, definition: ArtifactDefinition
) -> UUID:
    storage = (
        await tx.get(NodeStorageRow, placement.storage_uuid) if placement.storage_uuid else None
    )
    if (
        spec.id != placement.id
        or spec.node_uuid != placement.node_uuid
        or spec.project_uuid != placement.project_uuid
        or spec.release.module != definition.key
        or spec.workspace is None
        or spec.workspace.id != placement.storage_uuid
        or storage is None
        or storage.node_uuid != placement.node_uuid
        or storage.project_uuid != placement.project_uuid
        or storage.purpose != definition.storage_purpose
        or storage.retention != "persistent"
    ):
        raise NodeConflict("Current module storage owner binding required")
    return storage.id


class SqlPlacementUpdateTransactions(_DatabaseBinding[PlatformDatabase]):
    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PlacementUpdateSession]:
        async with self.database.transaction() as tx:
            yield SqlPlacementUpdateSession(tx)


class SqlPlacementUpdateSession(SqlPlacementMutationSession):
    def __init__(self, tx: AsyncSession) -> None:
        super().__init__(tx)
        self.existing: NodeOperationRow | None = None

    async def receipt(self, operation_uuid: UUID) -> UpdateReplay | None:
        self.existing = await self.tx.get(NodeOperationRow, operation_uuid)
        row = self.existing
        if row is None:
            return None
        return UpdateReplay(row.actor_uuid, row.placement_uuid, row.sequence)

    async def replay_fields(self, change: PlacementUpdate) -> UpdateReplayFields:
        row, placement = self.existing, self.placement
        if row is None or placement is None:
            raise ValueError("Update replay requires a receipt and locked placement")
        release = await self.tx.get(ModuleReleaseRow, change.release_uuid)
        desired = row.desired
        target_matches = (
            release is not None
            and release.artifact_key == placement.artifact_key
            and desired.release.image == release.image_reference
        )
        limits_match = None if change.limits is None else desired.limits == change.limits
        configuration_match = (
            None if change.configuration is None else desired.configuration == change.configuration
        )
        workspace_match: bool | None = None
        if change.project_workspace is not MISSING:
            workspace_match = desired.project_workspace == change.project_workspace
        return UpdateReplayFields(
            target_matches, limits_match, configuration_match, workspace_match
        )

    async def prepare(self, change: PlacementUpdate, actor: NodeActor) -> PreparedPlacementUpdate:
        placement, previous = self.placement, self.previous
        if placement is None or previous is None:
            raise ValueError("Update must lock and qualify the current placement")
        node = qualified_placement_node(await self.tx.get(NodeRow, placement.node_uuid), actor)
        approved = await approved_placement_release(
            self.tx, change.release_uuid, module=placement.artifact_key
        )
        definition = approved.definition
        spec = current_spec(placement, previous)
        storage_uuid = await current_update_storage(self.tx, placement, spec, definition)
        workspace = (
            change.project_workspace
            if change.project_workspace is not MISSING
            else spec.project_workspace
        )
        await require_project_workspace(
            self.tx,
            spec.project_workspace,
            module=definition.key,
            node_uuid=node.id,
            project_uuid=placement.project_uuid,
            private_storage_uuid=storage_uuid,
        )
        await require_project_workspace(
            self.tx,
            workspace,
            module=definition.key,
            node_uuid=node.id,
            project_uuid=placement.project_uuid,
            private_storage_uuid=storage_uuid,
        )
        configuration = (
            change.configuration if change.configuration is not None else spec.configuration
        )
        configuration = await resolved_configuration(self.tx, node.id, configuration)
        return PreparedPlacementUpdate(
            spec, approved.spec, configuration, workspace, definition.minimum_limits
        )

    async def stage(self, intent: UpdateIntent, previous: Deployment, desired: Deployment) -> None:
        placement = self.placement
        if (
            placement is None
            or placement.id != intent.placement_uuid
            or placement.project_uuid != intent.project_uuid
        ):
            raise ValueError("Update placement selectors changed")
        placement.sequence += 1
        placement.desired_release_uuid = intent.release_uuid
        placement.limits = desired.limits
        placement.state = "updating"
        operation = NodeOperationRow(
            id=intent.operation_uuid,
            node_uuid=placement.node_uuid,
            placement_uuid=placement.id,
            actor_uuid=intent.actor_uuid,
            sequence=placement.sequence,
            fingerprint=desired.fingerprint,
            desired=desired,
            previous=previous,
            phase="queued",
        )
        self.tx.add(operation)
        await self.tx.flush()
        audit_placement(self.tx, operation, placement, "queued")
