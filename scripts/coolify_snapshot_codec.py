"""Strict, metadata-only JSON adapter for saved Coolify evidence."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime

from coolify_snapshot import (
    ApplicationIdentity,
    DevelopmentScope,
    ExpectedApplication,
    SavedApplication,
    SnapshotEvidence,
    SnapshotExpectation,
)


class SnapshotFormatError(ValueError):
    """A fixed safe diagnostic; external values must not appear in output."""


@dataclass(frozen=True)
class JsonRecord:
    fields: tuple[tuple[str, object], ...]

    def __post_init__(self) -> None:
        names = tuple(key for key, _ in self.fields)
        if len(names) != len(set(names)):
            raise ValueError("duplicate snapshot JSON property")

    def value(self, name: str) -> object:
        for key, value in self.fields:
            if key == name:
                return value
        raise SnapshotFormatError("Coolify snapshot: invalid bounded metadata envelope")

    def string(self, name: str) -> str:
        value = self.value(name)
        if not isinstance(value, str):
            raise SnapshotFormatError(
                "Coolify snapshot: unexpected/missing field or non-string metadata"
            )
        return value


def _json_record(pairs: list[tuple[str, object]]) -> JsonRecord:
    return JsonRecord(tuple(pairs))


def decode_snapshot(text: str) -> object:
    value: object = json.loads(text, object_pairs_hook=_json_record)
    return value


def _record(value: object, *, fields: frozenset[str] | None, error: str) -> JsonRecord:
    if isinstance(value, JsonRecord):
        record = value
    elif isinstance(value, Mapping):
        pairs: list[tuple[str, object]] = []
        for key, item in value.items():
            if not isinstance(key, str):
                raise SnapshotFormatError(error)
            pairs.append((key, item))
        record = JsonRecord(tuple(pairs))
    else:
        raise SnapshotFormatError(error)
    if fields is not None and frozenset(key for key, _ in record.fields) != fields:
        raise SnapshotFormatError(error)
    return record


def _scope(value: object) -> DevelopmentScope:
    record = _record(
        value,
        fields=frozenset({"project", "environment", "repository"}),
        error="Coolify snapshot: authorized project/environment/repository mismatch",
    )
    return DevelopmentScope(
        *(record.string(name) for name in ("project", "environment", "repository"))
    )


def _items(value: object, error: str, *, bounded: bool = False) -> tuple[object, ...]:
    if not isinstance(value, list) or (bounded and len(value) > 14):
        raise SnapshotFormatError(error)
    return tuple(value)


def _identity(record: JsonRecord) -> ApplicationIdentity:
    return ApplicationIdentity(record.string("slug"), record.string("uuid"))


def _application(value: object) -> SavedApplication:
    record = _record(
        value,
        fields=frozenset(
            {
                "slug",
                "uuid",
                "name",
                "status",
                "watch_paths",
                "base_directory",
                "docker_compose_location",
                "git_repository",
                "git_branch",
            }
        ),
        error="Coolify snapshot: unexpected/missing field or non-string metadata",
    )
    return SavedApplication(
        _identity(record),
        record.string("name"),
        record.string("status"),
        record.string("watch_paths"),
        record.string("base_directory"),
        record.string("docker_compose_location"),
        record.string("git_repository"),
        record.string("git_branch"),
    )


def _unavailable(value: object) -> ApplicationIdentity:
    error = "Coolify snapshot: invalid bounded lookup-error record"
    record = _record(value, fields=frozenset({"slug", "uuid", "error_type"}), error=error)
    try:
        if record.string("error_type") not in {"http_404", "timeout", "unavailable"}:
            raise SnapshotFormatError(error)
        return _identity(record)
    except SnapshotFormatError:
        raise SnapshotFormatError(error) from None


def snapshot_evidence(value: object) -> SnapshotEvidence:
    record = _record(
        value,
        fields=frozenset({"scope", "captured_at_utc", "applications", "lookup_errors"}),
        error="Coolify snapshot: invalid bounded metadata envelope",
    )
    scope = _scope(record.value("scope"))
    try:
        stamp = record.string("captured_at_utc")
        when = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        raise SnapshotFormatError(
            "Coolify snapshot: timestamp missing, future or older than one hour"
        ) from None
    applications = tuple(
        _application(item)
        for item in _items(
            record.value("applications"),
            "Coolify snapshot: application list must be scoped and bounded",
            bounded=True,
        )
    )
    unavailable = tuple(
        _unavailable(item)
        for item in _items(
            record.value("lookup_errors"),
            "Coolify snapshot: invalid scoped lookup error list",
            bounded=True,
        )
    )
    return SnapshotEvidence(scope, when, applications, unavailable)


def snapshot_expectation(value: object) -> SnapshotExpectation:
    if isinstance(value, SnapshotExpectation):
        return value
    record = _record(value, fields=None, error="Coolify snapshot: invalid reviewed source plan")
    scope = _scope(record.value("scope"))
    candidates: list[ExpectedApplication] = []
    for item in _items(
        record.value("candidates"), "Coolify snapshot: invalid reviewed source plan"
    ):
        candidate = _record(
            item, fields=None, error="Coolify snapshot: invalid reviewed source plan"
        )
        raw_watches = _items(
            candidate.value("watch_paths"), "Coolify snapshot: invalid reviewed source plan"
        )
        watches: list[str] = []
        for watch in raw_watches:
            if not isinstance(watch, str):
                raise SnapshotFormatError("Coolify snapshot: invalid reviewed source plan")
            watches.append(watch)
        candidates.append(
            ExpectedApplication(
                _identity(candidate),
                candidate.string("base_directory"),
                candidate.string("compose_location"),
                tuple(watches),
            )
        )
    held = tuple(
        _identity(
            _record(item, fields=None, error="Coolify snapshot: invalid reviewed source plan")
        )
        for item in _items(record.value("held"), "Coolify snapshot: invalid reviewed source plan")
    )
    return SnapshotExpectation(scope, tuple(candidates), held)


def saved_snapshot_errors(
    snapshot: object, plan: object, *, targets: frozenset[str] | None
) -> list[str]:
    try:
        expected = snapshot_expectation(plan)
        evidence = snapshot_evidence(snapshot)
    except SnapshotFormatError as error:
        return [str(error)]
    return list(evidence.assess(expected, now=datetime.now(UTC), targets=targets))
