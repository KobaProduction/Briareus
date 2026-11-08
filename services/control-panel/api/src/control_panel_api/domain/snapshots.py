from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from briareus_json_values import StrictModel

from control_panel_api.domain.admin_data import AnalysisOverview, CoverageResult, FileStats

type SnapshotCategory = Literal["workspace_stats", "reverse_overview", "reverse_coverage"]
type SnapshotPayload = FileStats | AnalysisOverview | CoverageResult


class EmptySnapshotParameters(StrictModel):
    """Base snapshots have no arguments."""


class CoverageSnapshotParameters(StrictModel):
    project_id: str
    program: str
    full: bool


type SnapshotParameters = EmptySnapshotParameters | CoverageSnapshotParameters


def validate_snapshot_contract(
    category: SnapshotCategory, parameters: SnapshotParameters, payload: SnapshotPayload | None
) -> None:
    if category == "reverse_coverage":
        if not isinstance(parameters, CoverageSnapshotParameters):
            raise ValueError("coverage snapshots require coverage parameters")
        expected: type[SnapshotPayload] = CoverageResult
    else:
        if not isinstance(parameters, EmptySnapshotParameters):
            raise ValueError("base snapshots cannot have coverage parameters")
        expected = FileStats if category == "workspace_stats" else AnalysisOverview
    if payload is not None and not isinstance(payload, expected):
        raise ValueError(f"{category} snapshot has an incompatible payload")


@dataclass
class CachedSnapshot:
    key: str
    category: SnapshotCategory
    parameters: SnapshotParameters = field(default_factory=EmptySnapshotParameters)
    payload: SnapshotPayload | None = None
    refresh_after_seconds: int = 300
    status: str = "pending"
    updated_at: datetime | None = None
    attempted_at: datetime | None = None
    error_type: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        validate_snapshot_contract(self.category, self.parameters, self.payload)

    def age_seconds(self, now: datetime | None = None) -> float | None:
        if self.updated_at is None:
            return None
        current = now or datetime.now(UTC)
        updated = self.updated_at
        if updated.tzinfo is None:
            updated = updated.replace(tzinfo=UTC)
        return max(0.0, (current - updated).total_seconds())

    def stale(self, now: datetime | None = None) -> bool:
        age = self.age_seconds(now)
        return age is None or age >= self.refresh_after_seconds


class SnapshotMetadata(StrictModel):
    status: str
    updated_at: str | None
    attempted_at: str | None
    age_seconds: float | None
    stale: bool
    error_type: str
    error_message: str
