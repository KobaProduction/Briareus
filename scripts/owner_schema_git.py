"""Read bounded source text from exact local Git objects, without executing it."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from collections.abc import Mapping
from pathlib import Path
from typing import cast

from owner_image_history import reviewed_chain
from owner_schema_policy import OwnerHistory

_PACKAGE = re.compile(r"COPY\s+services/([a-z-]+)/migrations/versions/([A-Za-z0-9_]+\.py)\b")
_LEGACY_RESOURCES = re.compile(
    r"COPY\s+scripts/alembic_owners/resources/versions/([A-Za-z0-9_]+\.py)\b"
)


def _field(value: object, name: str) -> object:
    return cast(Mapping[object, object], value).get(name) if isinstance(value, Mapping) else None


def _legacy_registration(value: object) -> bool:
    return all(
        _field(value, key) == expected
        for key, expected in (
            ("name", "Resource Catalog"),
            ("module", "resources"),
            ("base_directory", "/deploy/resources"),
            ("dockerfile", "deploy/resources/Dockerfile"),
            ("docker_compose_location", "/docker-compose.coolify.yaml"),
        )
    )


def _legacy_registry(source: str | None) -> bool:
    if source is None:
        return False
    try:
        decoded: object = json.loads(source)
    except ValueError:
        return False
    apps = _field(decoded, "applications")
    if _field(decoded, "environment") != "development" or not isinstance(apps, list):
        return False
    return sum(_legacy_registration(item) for item in cast(list[object], apps)) == 1


def _history(source: str | None, owner: str) -> tuple[str, ...] | None:
    if source is None:
        return None
    try:
        return reviewed_chain(source, "access" if owner == "authorization" else owner)
    except (ValueError, TypeError, SyntaxError, MemoryError):
        return None


class GitOwnerSources:
    def __init__(self, root: Path) -> None:
        self._root = root
        executable = shutil.which("git")
        if executable is None:
            raise FileNotFoundError("local Git source reader is unavailable")
        self._git = str(Path(executable).resolve())

    def _command(self, *args: str) -> str | None:
        result = subprocess.run(  # noqa: S603 -- fixed local Git reads, exact SHA/path argv, no shell
            [self._git, "-C", str(self._root), *args],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
        return result.stdout if result.returncode == 0 and len(result.stdout) < 300000 else None

    def _read(self, sha: str, path: str) -> str | None:
        return self._command("show", f"{sha}:{path}")

    def read_blob(self, sha: str, path: str, *, limit: int) -> str | None:
        source = self._read(sha, path)
        return source if source is not None and len(source) < limit else None

    def has_commit(self, sha: str) -> bool:
        return self._command("rev-parse", "--verify", sha + "^{commit}") is not None

    def history(self, sha: str, owner: str, *, allow_legacy: bool) -> OwnerHistory:
        chain = _history(self._read(sha, "services/common/owner_migrations.py"), owner)
        docker = self._read(sha, f"services/{owner}/Dockerfile")
        legacy = (
            allow_legacy
            and owner == "resources"
            and docker is None
            and _legacy_registry(self._read(sha, "deploy/APPLICATIONS.json"))
        )
        if legacy:
            docker = self._read(sha, "deploy/resources/Dockerfile")
        if docker is None:
            packaged = None
        elif legacy:
            packaged = tuple(_LEGACY_RESOURCES.findall(docker))
        else:
            packaged = tuple(
                name for name_owner, name in _PACKAGE.findall(docker) if name_owner == owner
            )
        return OwnerHistory(chain, packaged, legacy)

    def migration(self, sha: str, owner: str, filename: str, *, legacy: bool) -> str | None:
        prefix = "scripts/alembic_owners/resources" if legacy else f"services/{owner}/migrations"
        return self._read(sha, f"{prefix}/versions/{filename}")
