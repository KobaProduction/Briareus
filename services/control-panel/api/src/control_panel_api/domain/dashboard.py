from briareus_json_values import StrictModel

from .admin_data.analysis import AnalysisOverview
from .admin_data.files import FileStats
from .snapshots import SnapshotMetadata
from .telemetry import InvocationSummary


class EmptyData(StrictModel):
    """Wire-compatible empty state while the first snapshot is being collected."""


class AccountSummary(StrictModel):
    total: int
    enabled: int
    by_provider: dict[str, int]


class AnalysisSummary(StrictModel):
    projects: int
    active_sessions: int
    workers: int
    running_workers: int

    @classmethod
    def from_overview(cls, overview: AnalysisOverview | None) -> "AnalysisSummary":
        return cls(
            projects=len(overview.projects) if overview else 0,
            active_sessions=sum(p.session == "active" for p in overview.projects)
            if overview
            else 0,
            workers=len(overview.workers) if overview else 0,
            running_workers=sum(w.running for w in overview.workers) if overview else 0,
        )


class DashboardState(StrictModel):
    accounts: AccountSummary
    calls: InvocationSummary
    workspace: FileStats | EmptyData
    workspace_meta: SnapshotMetadata | EmptyData
    analysis: AnalysisSummary
    analysis_meta: SnapshotMetadata | EmptyData
