"""Validate persisted publication and approved catalog inputs before placement use."""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from node_protocol import ModuleRelease
from node_protocol.catalog import ARTIFACTS
from projects._node_persistence import ModuleArtifactRow, ModuleReleaseRow
from projects.application.placement_execution import ApprovedPlacementRelease
from projects.domain.module_catalog import CatalogError, StoredArtifact, require_deployable
from projects.infrastructure.catalog_records import artifact_definition, stored_inputs
from projects.infrastructure.module_catalog import release_summary


async def approved_placement_release(
    tx: AsyncSession, release_uuid: UUID, *, module: str | None = None
) -> ApprovedPlacementRelease:
    release = await tx.get(ModuleReleaseRow, release_uuid)
    key = module if module is not None else release.artifact_key if release else None
    artifact = await tx.get(ModuleArtifactRow, key) if key is not None else None
    source = ARTIFACTS.get(key) if key is not None else None
    if release is None or release.image_reference is None or artifact is None or source is None:
        raise CatalogError("Approved published node adapter required")
    definition = artifact_definition(source)
    require_deployable(
        release_summary(release),
        StoredArtifact(artifact.key, artifact.enabled, stored_inputs(artifact.inputs)),
        definition,
    )
    return ApprovedPlacementRelease(
        release.id,
        ModuleRelease(module=source.key, image=release.image_reference, lifecycle=source.lifecycle),
        definition,
    )
