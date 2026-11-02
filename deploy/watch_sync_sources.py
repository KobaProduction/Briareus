"""Resolve approved identities from checked-in scope before credentials are read."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from pathlib import Path

from watch_sync_domain import (
    ENVIRONMENT_UUID,
    PROJECT_UUID,
    REPOSITORY,
    ApplicationIdentity,
    ApprovedWatchTarget,
    SavedWatchMetadata,
    SyncError,
)


def _field(value: object, name: str) -> object:
    if not isinstance(value, Mapping):
        raise SyncError("invalid bounded application metadata object")
    return value.get(name)


def _string(value: object, name: str) -> str:
    field = _field(value, name)
    if not isinstance(field, str):
        raise SyncError("missing or invalid application metadata string")
    return field


def _items(value: object) -> tuple[object, ...]:
    if not isinstance(value, list):
        raise SyncError("invalid approved application source list")
    return tuple(value)


def _identity(value: object) -> ApplicationIdentity:
    return ApplicationIdentity(_string(value, "slug"), _string(value, "uuid"))


def read_watch_paths(path: Path) -> tuple[str, ...]:
    source = path.read_text(encoding="utf-8")
    matches = tuple(re.finditer(r"^x-watch-path-coolify:\s*$", source, re.MULTILINE))
    if len(matches) != 1 or matches[0].start() != 0:
        raise SyncError("exactly one top-level x-watch-path-coolify is required")
    paths: list[str] = []
    for line in source[matches[0].end() :].splitlines():
        if not line.strip():
            if paths:
                break
            continue
        if not line.startswith("  - "):
            break
        value: object = json.loads(line[4:])
        if not isinstance(value, str):
            raise SyncError("watch path list needs JSON-quoted scalar items")
        paths.append(value)
    return tuple(paths)


def _require_scope(plan: object, documented: frozenset[ApplicationIdentity]) -> tuple[object, ...]:
    scope = _field(plan, "scope")
    actual = (
        _string(scope, "project"),
        _string(scope, "environment"),
        _string(scope, "repository"),
    )
    if actual != (PROJECT_UUID, ENVIRONMENT_UUID, REPOSITORY):
        raise SyncError("source plan does not match the approved Development scope")
    candidates = _items(_field(plan, "candidates"))
    identities = tuple(_identity(item) for item in (*candidates, *_items(_field(plan, "held"))))
    if (
        len(identities) != 14
        or len({item.uuid for item in identities}) != 14
        or frozenset(identities) != documented
    ):
        raise SyncError("source plan differs from the exact fourteen-Application allowlist")
    return candidates


def load_approved_target(root: Path, compose: Path, uuid: str, branch: str) -> ApprovedWatchTarget:
    policy = (root / "docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md").read_text()
    documented = frozenset(
        ApplicationIdentity(slug, key)
        for slug, key in re.findall(r"\| ([a-z][\w-]*) \| [^|]+ \| ([a-z0-9]{24}) \|", policy)
    )
    value: object = json.loads((root / "docs/operations/flat-batch-cutover.json").read_text())
    candidates = _require_scope(value, documented)
    candidate = next((item for item in candidates if _identity(item).uuid == uuid), None)
    if candidate is None:
        raise SyncError("Application UUID is not an approved active Development candidate")
    folder = _string(candidate, "folder")
    if (
        _string(candidate, "base_directory") != "/" + folder
        or _string(candidate, "compose_location") != "/docker-compose.coolify.yaml"
    ):
        raise SyncError("reviewed Application Base/Compose paths do not match its source folder")
    expected = (root / folder / "docker-compose.coolify.yaml").resolve()
    if not expected.is_relative_to(root.resolve()) or compose.resolve() != expected:
        raise SyncError("Compose source does not belong to the exact approved Application")
    paths = read_watch_paths(expected)
    expected_paths = _items(_field(candidate, "watch_paths"))
    if paths != expected_paths:
        raise SyncError("native Watch Paths differ from the reviewed flat source plan")
    if f"{folder}/**" not in paths:
        raise SyncError("module-local directory watch is required")
    return ApprovedWatchTarget(
        _identity(candidate),
        _string(candidate, "base_directory"),
        _string(candidate, "compose_location"),
        branch,
        paths,
    )


def decode_metadata(raw: bytes) -> SavedWatchMetadata:
    value: object = json.loads(raw)
    return SavedWatchMetadata(
        *(
            _string(value, name)
            for name in (
                "uuid",
                "git_repository",
                "git_branch",
                "base_directory",
                "docker_compose_location",
                "build_pack",
                "watch_paths",
            )
        )
    )
