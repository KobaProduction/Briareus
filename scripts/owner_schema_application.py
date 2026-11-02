"""Collect exact-revision owner evidence through a source repository port."""

from __future__ import annotations

from typing import Protocol

from owner_schema_policy import (
    MigrationSource,
    OwnerAssessment,
    OwnerComparison,
    OwnerHistory,
    OwnerSourceEvidence,
)


class OwnerSources(Protocol):
    def has_commit(self, sha: str) -> bool: ...

    def history(self, sha: str, owner: str, *, allow_legacy: bool) -> OwnerHistory: ...

    def migration(self, sha: str, owner: str, filename: str, *, legacy: bool) -> str | None: ...


class AssessOwnerSchema:
    def __init__(self, sources: OwnerSources) -> None:
        self._sources = sources

    def execute(self, comparison: OwnerComparison) -> OwnerAssessment:
        if not self._sources.has_commit(comparison.previous):
            raise ValueError("previous deployment git commit is not locally available")
        if not self._sources.has_commit(comparison.candidate):
            raise ValueError("candidate git commit is not locally available")
        previous = self._sources.history(comparison.previous, comparison.owner, allow_legacy=True)
        candidate = self._sources.history(
            comparison.candidate, comparison.owner, allow_legacy=False
        )
        migrations = self._migration_sources(comparison, previous, candidate)
        return OwnerSourceEvidence(comparison, previous, candidate, migrations).assess()

    def _migration_sources(
        self, comparison: OwnerComparison, previous: OwnerHistory, candidate: OwnerHistory
    ) -> tuple[MigrationSource, ...]:
        if (
            not previous.available
            or not candidate.available
            or not previous.reviewed
            or not candidate.reviewed
        ):
            return ()
        return tuple(
            MigrationSource(
                filename,
                self._sources.migration(
                    comparison.previous,
                    comparison.owner,
                    filename,
                    legacy=previous.legacy_resources,
                ),
                self._sources.migration(
                    comparison.candidate, comparison.owner, filename, legacy=False
                ),
            )
            for filename in previous.packaged or ()
            if filename.endswith(".py")
        )
