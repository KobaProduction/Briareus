"""Resolve project workspace attachments without granting cross-project or private access."""

from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from node_protocol import WorkspaceMount
from projects._node_persistence import NodeStorageRow
from projects.domain.node_administration import NodeConflict, NodeInvalid
from projects.domain.placement_admission import PlacementWorkspace

INITIAL_PROJECT_STORAGE_QUOTA = 1024**3


async def ensure_project_storage(
    tx: AsyncSession, node_uuid: UUID, project_uuid: UUID, purpose: str
) -> UUID:
    storage = await tx.scalar(
        select(NodeStorageRow).where(
            NodeStorageRow.node_uuid == node_uuid,
            NodeStorageRow.project_uuid == project_uuid,
            NodeStorageRow.purpose == purpose,
        )
    )
    if storage is None:
        storage = NodeStorageRow(
            id=uuid4(),
            node_uuid=node_uuid,
            project_uuid=project_uuid,
            purpose=purpose,
            quota_bytes=INITIAL_PROJECT_STORAGE_QUOTA,
            retention="persistent",
        )
        tx.add(storage)
        await tx.flush()
    return storage.id


async def require_project_workspace(
    tx: AsyncSession,
    mount: WorkspaceMount | None,
    *,
    module: str,
    node_uuid: UUID,
    project_uuid: UUID,
    private_storage_uuid: UUID,
) -> WorkspaceMount | None:
    if mount is None:
        return None
    if module not in {"web", "reverse"} or mount.id == private_storage_uuid:
        raise NodeInvalid("Web and Analysis can attach a separate project workspace")
    storage = await tx.get(NodeStorageRow, mount.id)
    if storage is None:
        raise NodeConflict("Shared workspace must belong to this project and node")
    workspace = PlacementWorkspace(
        storage.node_uuid, storage.project_uuid, storage.purpose, storage.retention
    )
    workspace.require_project_binding(node_uuid, project_uuid)
    return mount
