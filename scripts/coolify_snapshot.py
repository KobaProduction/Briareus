"""Policies for evidence collected from the exact approved Development apps."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta


@dataclass(frozen=True)
class ApplicationIdentity:
    slug: str
    uuid: str


@dataclass(frozen=True)
class DevelopmentScope:
    project: str
    environment: str
    repository: str


@dataclass(frozen=True)
class ExpectedApplication:
    identity: ApplicationIdentity
    base_directory: str
    compose_location: str
    watch_paths: tuple[str, ...]


@dataclass(frozen=True)
class SnapshotExpectation:
    scope: DevelopmentScope
    candidates: tuple[ExpectedApplication, ...]
    held: tuple[ApplicationIdentity, ...]

    @property
    def identities(self) -> frozenset[ApplicationIdentity]:
        return frozenset(item.identity for item in self.candidates) | frozenset(self.held)


@dataclass(frozen=True)
class SavedApplication:
    identity: ApplicationIdentity
    name: str
    status: str
    watch_paths: str
    base_directory: str
    compose_location: str
    repository: str
    branch: str

    def configuration_errors(
        self, expected: ExpectedApplication, repository: str
    ) -> tuple[str, ...]:
        prefix = self.identity.slug + ": "
        errors = [
            prefix + "saved Coolify " + field + " differs from source"
            for field, actual, desired in (
                ("base_directory", self.base_directory, expected.base_directory),
                ("docker_compose_location", self.compose_location, expected.compose_location),
                ("git_repository", self.repository, repository),
                ("git_branch", self.branch, "main"),
            )
            if actual != desired
        ]
        watches = tuple(part.strip() for part in self.watch_paths.splitlines() if part.strip())
        if len(watches) != len(set(watches)):
            errors.append(prefix + "duplicate persisted Watch Paths")
        errors.extend(
            prefix + "saved Watch Paths missing " + name
            for name in expected.watch_paths
            if name not in watches
        )
        if set(watches) - set(expected.watch_paths):
            errors.append(prefix + "unreviewed persisted Watch Paths present")
        return tuple(errors)


@dataclass(frozen=True)
class SnapshotEvidence:
    scope: DevelopmentScope
    captured_at: datetime
    applications: tuple[SavedApplication, ...]
    unavailable: tuple[ApplicationIdentity, ...]

    def authority_errors(self, expected: SnapshotExpectation, *, now: datetime) -> tuple[str, ...]:
        if self.scope != expected.scope:
            return ("Coolify snapshot: authorized project/environment/repository mismatch",)
        if self.captured_at.tzinfo is None:
            return ("Coolify snapshot: timestamp missing, future or older than one hour",)
        age = now.astimezone(UTC) - self.captured_at
        if not -timedelta(minutes=2) <= age <= timedelta(hours=1):
            return ("Coolify snapshot: timestamp missing, future or older than one hour",)
        actual = tuple(item.identity for item in self.applications)
        if len(actual) != len(set(actual)):
            return ("Coolify snapshot: duplicate Application slug/UUID",)
        if not set(actual) <= expected.identities:
            return ("Coolify snapshot: unapproved or mislabeled Application UUID",)
        missing = expected.identities - set(actual)
        if (
            len(self.unavailable) != len(set(self.unavailable))
            or not set(self.unavailable) <= missing
        ):
            return ("Coolify snapshot: error must match one unavailable approved UUID",)
        if set(self.unavailable) != missing:
            return ("Coolify snapshot: missing approved Application without read evidence",)
        return ()

    def assess(
        self,
        expected: SnapshotExpectation,
        *,
        now: datetime,
        targets: frozenset[str] | None,
    ) -> tuple[str, ...]:
        rejected = self.authority_errors(expected, now=now)
        if rejected:
            return rejected
        errors = [
            identity.slug + ": approved Dev Application metadata unverified (exact UUID)"
            for identity in sorted(self.unavailable, key=lambda item: (item.slug, item.uuid))
            if targets is None or identity.slug in targets
        ]
        actual = {item.identity: item for item in self.applications}
        for candidate in expected.candidates:
            if targets is not None and candidate.identity.slug not in targets:
                continue
            application = actual.get(candidate.identity)
            if application is not None:
                errors.extend(
                    application.configuration_errors(candidate, expected.scope.repository)
                )
        # Held apps prove presence only; they never authorize configuration changes.
        return tuple(errors)
