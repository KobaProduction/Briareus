"""HTTP projection of the existing workspace listing and typed cached statistics."""

from application.snapshot_views import MissingSnapshotPayload, SnapshotMetadataView
from application.workspace_views import FileWorkspaceStats
from pydantic import BaseModel, ConfigDict

from modules.workspace_compat.domain.receipts import WorkspacePage


class WorkspaceListing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    listing: WorkspacePage
    current_path: str
    parent_path: str
    stats: FileWorkspaceStats | MissingSnapshotPayload
    stats_meta: SnapshotMetadataView
