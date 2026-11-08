from typing import Literal

from briareus_json_values import JsonObject, JsonValue, StrictModel
from briareus_service_discovery import DiscoveredService

from control_panel_api.domain.admin_data.analysis import (
    AnalysisOverview,
    AnalysisSession,
    AnalysisWorker,
    CoverageResult,
)
from control_panel_api.domain.admin_data.files import FileListing, FileStats
from control_panel_api.domain.dashboard import EmptyData
from control_panel_api.domain.snapshots import SnapshotMetadata


class NodeIdentity(StrictModel):
    id: str
    hostname: str
    origin: str


class BootstrapState(StrictModel):
    product: str
    environment: str
    node: NodeIdentity
    services: list[DiscoveredService]
    checked_at: str


class FilesView(StrictModel):
    listing: FileListing
    current_path: str
    parent_path: str
    stats: FileStats | EmptyData
    stats_meta: SnapshotMetadata | EmptyData


class AnalysisView(StrictModel):
    overview: AnalysisOverview | EmptyData
    meta: SnapshotMetadata | EmptyData


class CoverageView(StrictModel):
    coverage: CoverageResult | EmptyData
    meta: SnapshotMetadata | EmptyData


class AnalysisProjectView(StrictModel):
    session: AnalysisSession
    # Provider-owned files and program details are opaque MCP payloads.
    files: JsonObject
    programs: list[JsonValue]
    folder: str


class AnalysisWorkersView(StrictModel):
    workers: list[AnalysisWorker]
    count: int


class AnalysisWorkerOperation(StrictModel):
    operation: Literal["clear_queue", "recover"]
    result: JsonObject
    worker: AnalysisWorker
