"""Versioned codecs for the three existing cache categories and coverage queries."""

import json
from typing import Literal

from application.analysis_views import AnalysisOverview
from application.snapshot_contracts import SnapshotContent
from application.workspace_views import FileWorkspaceStats
from domain.analysis import CoverageReport, CoverageRequest
from domain.snapshots import SnapshotCategory
from pydantic import BaseModel, ConfigDict, TypeAdapter, ValidationError


class StoredSnapshot[T](BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal[1] = 1
    snapshot: T | None = None


def _decode[T](raw: str, model: type[StoredSnapshot[T]], legacy: type[T]) -> T | None:
    try:
        document = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(document, dict) or not document:
        return None
    if "schema_version" in document:
        return model.model_validate_json(raw).snapshot
    # Existing cache rows precede the explicit envelope. Only the same concrete
    # category model is accepted; arbitrary JSON never leaves this adapter.
    try:
        return TypeAdapter(legacy).validate_json(raw)
    except ValidationError:
        return None


def decode_coverage_request(raw: str) -> CoverageRequest | None:
    return _decode(raw, StoredSnapshot[CoverageRequest], CoverageRequest)


def encode_coverage_request(request: CoverageRequest | None) -> str:
    return StoredSnapshot[CoverageRequest](snapshot=request).model_dump_json()


def decode_snapshot(category: SnapshotCategory, raw: str) -> SnapshotContent | None:
    match category:
        case "workspace_stats":
            return _decode(raw, StoredSnapshot[FileWorkspaceStats], FileWorkspaceStats)
        case "reverse_overview":
            return _decode(raw, StoredSnapshot[AnalysisOverview], AnalysisOverview)
        case "reverse_coverage":
            return _decode(raw, StoredSnapshot[CoverageReport], CoverageReport)


def encode_snapshot(category: SnapshotCategory, content: SnapshotContent) -> str:
    match category, content:
        case "workspace_stats", FileWorkspaceStats():
            return StoredSnapshot[FileWorkspaceStats](snapshot=content).model_dump_json()
        case "reverse_overview", AnalysisOverview():
            return StoredSnapshot[AnalysisOverview](snapshot=content).model_dump_json()
        case "reverse_coverage", CoverageReport():
            return StoredSnapshot[CoverageReport](snapshot=content).model_dump_json()
        case _:
            raise ValueError("Cached snapshot content does not match its category")


def snapshot_category(value: str) -> SnapshotCategory:
    match value:
        case "workspace_stats" | "reverse_overview" | "reverse_coverage":
            return value
        case _:
            raise ValueError(f"Unsupported cached snapshot category: {value}")
