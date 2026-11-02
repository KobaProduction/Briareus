from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Literal

from domain.analysis import CoverageRequest

type SnapshotCategory = Literal["workspace_stats", "reverse_overview", "reverse_coverage"]


@dataclass
class CachedSnapshot[T]:
    key: str
    category: SnapshotCategory
    coverage: CoverageRequest | None = None
    content: T | None = None
    refresh_after_seconds: int = 300
    status: str = "pending"
    updated_at: datetime | None = None
    attempted_at: datetime | None = None
    error_type: str = ""
    error_message: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

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
        return self.content is None or age is None or age >= self.refresh_after_seconds

    def due(self, now: datetime, *, retry_after_seconds: int) -> bool:
        attempted = self.attempted_at
        if attempted is not None and attempted.tzinfo is None:
            attempted = attempted.replace(tzinfo=UTC)
        retry_elapsed = (
            attempted is None or (now - attempted).total_seconds() >= retry_after_seconds
        )
        return retry_elapsed and self.stale(now)
