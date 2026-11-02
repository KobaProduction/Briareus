"""Forward-only compatibility of shipped owner source, never live database authority."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

OWNERS = frozenset({"platform", "resources", "authorization"})


class CompatibilityState(StrEnum):
    COMPATIBLE = "SOURCE_COMPATIBLE"
    INCOMPATIBLE = "SOURCE_INCOMPATIBLE"
    UNVERIFIED = "UNVERIFIED"


@dataclass(frozen=True)
class OwnerComparison:
    owner: str
    previous: str
    candidate: str

    def __post_init__(self) -> None:
        if self.owner not in OWNERS:
            raise ValueError("unknown, non-allowlisted owner")
        if not all(
            re.fullmatch(r"[0-9a-f]{40}", sha, re.ASCII) for sha in (self.previous, self.candidate)
        ):
            raise ValueError("pinned exact 40-digit git SHA required")


@dataclass(frozen=True)
class OwnerHistory:
    reviewed: tuple[str, ...] | None
    packaged: tuple[str, ...] | None
    legacy_resources: bool = False

    @property
    def available(self) -> bool:
        return self.reviewed is not None and self.packaged is not None


@dataclass(frozen=True)
class MigrationSource:
    filename: str
    previous: str | None
    candidate: str | None

    def issues(self) -> tuple[str, ...]:
        if self.candidate is None:
            return ("previously_packaged_migration_removed:" + self.filename,)
        if self.previous is None or self.previous != self.candidate:
            return ("previously_packaged_migration_rewritten:" + self.filename,)
        return ()


def image_migration_issues(
    previous_copies: tuple[str, ...], candidate_copies: tuple[str, ...], reviewed: tuple[str, ...]
) -> tuple[str, ...]:
    issues: list[str] = []
    if any(name not in candidate_copies for name in previous_copies if name.endswith(".py")):
        issues.append("candidate_image_drops_historical_migration_copy")
    if len(candidate_copies) != len(reviewed):
        issues.append("candidate_image_migration_count_differs_from_reviewed_chain")
    return tuple(issues)


@dataclass(frozen=True)
class OwnerAssessment:
    comparison: OwnerComparison
    previous_history: OwnerHistory
    candidate_history: OwnerHistory
    state: CompatibilityState
    findings: tuple[str, ...]


@dataclass(frozen=True)
class OwnerSourceEvidence:
    comparison: OwnerComparison
    previous: OwnerHistory
    candidate: OwnerHistory
    migrations: tuple[MigrationSource, ...]

    def assess(self) -> OwnerAssessment:
        if not self.previous.available or not self.candidate.available:
            return self._result(
                CompatibilityState.UNVERIFIED,
                ("historical_or_current_owner_source_or_packaged_image_unavailable",),
            )
        prior, current = self.previous.reviewed, self.candidate.reviewed
        if not prior or not current:
            return self._result(
                CompatibilityState.UNVERIFIED, ("owner_migration_history_cannot_be_established",)
            )
        issues = [
            "previously_reviewed_revision_removed:" + revision
            for revision in prior
            if revision not in current
        ]
        if current[: len(prior)] != prior:
            issues.append("candidate_revision_chain_is_not_forward_extension")
        for migration in self.migrations:
            issues.extend(migration.issues())
        issues.extend(
            image_migration_issues(
                self.previous.packaged or (), self.candidate.packaged or (), current
            )
        )
        state = CompatibilityState.INCOMPATIBLE if issues else CompatibilityState.COMPATIBLE
        return self._result(state, tuple(sorted(set(issues))))

    def _result(self, state: CompatibilityState, findings: tuple[str, ...]) -> OwnerAssessment:
        return OwnerAssessment(self.comparison, self.previous, self.candidate, state, findings)
