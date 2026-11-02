"""Closed set of cached administration read models, without serialized documents."""

from domain.analysis import CoverageReport
from domain.snapshots import CachedSnapshot

from application.analysis_views import AnalysisOverview
from application.workspace_views import FileWorkspaceStats

type SnapshotContent = FileWorkspaceStats | AnalysisOverview | CoverageReport
type AdminSnapshot = CachedSnapshot[SnapshotContent]
