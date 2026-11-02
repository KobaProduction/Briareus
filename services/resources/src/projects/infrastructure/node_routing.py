"""Read current Resources placement evidence; no permissions or credentials are minted."""

import json
import os
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from common.platform_db import PlatformDatabase
from node_protocol import ResourceLimits
from node_protocol.catalog import ARTIFACTS
from projects._node_persistence import (
    ModuleArtifactRow,
    ModuleReleaseRow,
    NodeModuleRow,
    NodeOperationRow,
    NodeRow,
    NodeStorageRow,
    ProjectModuleBindingRow,
)
from projects.domain.node_administration import NodeCapacity
from projects.domain.node_routing import (
    AppliedRoute,
    RouteArtifact,
    RoutedModule,
    RouteEvidence,
    RouteNode,
    RoutePlacement,
    RouteRelease,
    RouteStorage,
)
from service_runtime.platform_db_mechanics import _PrivateDatabaseBinding


def approved_origins() -> frozenset[str]:
    raw = json.loads(os.environ.get("BRIAREUS_NODE_ORIGINS", "[]"))
    if not isinstance(raw, list) or len(raw) > 100:
        raise ValueError("Explicit approved origins required")
    return frozenset(origin for origin in raw if isinstance(origin, str))


def route_capacity(limits: ResourceLimits) -> NodeCapacity:
    return NodeCapacity(limits.memory_bytes, limits.cpu_millis, limits.pids)


def applied_route(row: NodeOperationRow) -> AppliedRoute:
    spec = row.desired
    return AppliedRoute(
        spec.node_uuid,
        spec.id,
        spec.project_uuid,
        spec.release.module,
        spec.release.image,
        spec.release.port,
        spec.enabled,
        spec.fingerprint,
        row.fingerprint,
        row.sequence,
        route_capacity(spec.limits),
        spec.workspace.id if spec.workspace else None,
        spec.effect_verify_key or "",
    )


def route_storage(row: NodeStorageRow) -> RouteStorage:
    return RouteStorage(
        row.id, row.node_uuid, row.project_uuid, row.purpose, row.retention == "persistent"
    )


class SqlRouteEvidence(_PrivateDatabaseBinding[PlatformDatabase]):
    async def read(
        self,
        project_uuid: UUID,
        module: RoutedModule,
        *,
        workspace: bool,
    ) -> RouteEvidence | None:
        origins = approved_origins()
        async with self._database.transaction() as tx:
            placement = await tx.scalar(
                select(NodeModuleRow)
                .join(
                    ProjectModuleBindingRow,
                    ProjectModuleBindingRow.placement_uuid == NodeModuleRow.id,
                )
                .where(
                    ProjectModuleBindingRow.project_uuid == project_uuid,
                    ProjectModuleBindingRow.logical_key == module,
                    NodeModuleRow.project_uuid == project_uuid,
                    NodeModuleRow.artifact_key == module,
                    NodeModuleRow.state == "ready",
                )
            )
            if placement is None or placement.applied_release_uuid is None:
                return None
            node = await tx.get(NodeRow, placement.node_uuid)
            release = await tx.get(ModuleReleaseRow, placement.applied_release_uuid)
            artifact = await tx.get(ModuleArtifactRow, placement.artifact_key)
            applied = await tx.scalar(
                select(NodeOperationRow)
                .where(
                    NodeOperationRow.placement_uuid == placement.id,
                    NodeOperationRow.node_uuid == placement.node_uuid,
                    NodeOperationRow.phase == "succeeded",
                )
                .order_by(NodeOperationRow.sequence.desc())
                .limit(1)
            )
            proof = applied_route(applied) if applied is not None else None
            expiry = int(datetime.now(UTC).timestamp()) + 5
            storage = (
                await tx.get(NodeStorageRow, proof.storage_uuid)
                if workspace and proof is not None and proof.storage_uuid
                else None
            )
            return RouteEvidence(
                RoutePlacement(
                    placement.id,
                    placement.node_uuid,
                    placement.project_uuid,
                    placement.artifact_key,
                    placement.storage_uuid,
                    route_capacity(ResourceLimits.model_validate(placement.limits)),
                ),
                RouteNode(
                    node.id,
                    node.enabled,
                    node.deleted_at is not None,
                    bool(node.public_key),
                    node.endpoint in origins,
                    node.endpoint,
                )
                if node is not None
                else None,
                RouteRelease(
                    release.state == "published", release.artifact_key, release.image_reference
                )
                if release is not None
                else None,
                RouteArtifact(artifact.enabled, ARTIFACTS[module].storage_purpose or "")
                if artifact is not None
                else None,
                proof,
                route_storage(storage) if storage is not None else None,
                expiry,
            )
