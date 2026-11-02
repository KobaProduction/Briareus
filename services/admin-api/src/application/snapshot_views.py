"""Read models for cached data; an absent snapshot retains its empty wire object."""

from pydantic import BaseModel, ConfigDict

from application.analysis_views import AnalysisCoverage, AnalysisOverview

from .snapshot_contracts import AdminSnapshot

WORKSPACE_STATS_KEY = "workspace:stats"
REVERSE_OVERVIEW_KEY = "reverse:overview"


class MissingSnapshotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapshotMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    status: str
    updated_at: str | None
    attempted_at: str | None
    age_seconds: float | None
    stale: bool
    error_type: str
    error_message: str


type SnapshotMetadataView = SnapshotMetadata | MissingSnapshotMetadata


def snapshot_meta(snapshot: AdminSnapshot | None) -> SnapshotMetadataView:
    if snapshot is None:
        return MissingSnapshotMetadata()
    age = snapshot.age_seconds()
    return SnapshotMetadata(
        status=snapshot.status,
        updated_at=snapshot.updated_at.isoformat() if snapshot.updated_at else None,
        attempted_at=snapshot.attempted_at.isoformat() if snapshot.attempted_at else None,
        age_seconds=round(age, 1) if age is not None else None,
        stale=snapshot.stale(),
        error_type=snapshot.error_type,
        error_message=snapshot.error_message,
    )


class MissingSnapshotPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AnalysisOverviewSnapshot(BaseModel):
    overview: AnalysisOverview | MissingSnapshotPayload
    meta: SnapshotMetadataView


class AnalysisCoverageSnapshot(BaseModel):
    coverage: AnalysisCoverage | MissingSnapshotPayload
    meta: SnapshotMetadataView
