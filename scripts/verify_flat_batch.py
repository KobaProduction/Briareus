#!/usr/bin/env python3
"""One read-only, source-based acceptance gate for the flat Coolify migration.

This is not a test suite, deploy client, or a provider of fake OAuth grants.
No Coolify API queries or writes are performed; validation does not accept live cutover.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Literal

from coolify_snapshot import ApplicationIdentity
from coolify_snapshot_codec import decode_snapshot, saved_snapshot_errors
from flat_release_plan import ReleaseCandidate, ReleasePlan
from flat_release_source import decode_release_plan
from owner_image_history import MigrationHistory, migration_revision, reviewed_chain

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "docs/operations/flat-batch-cutover.json"
SCOPE = ROOT / "docs/operations/BRIAREUS_DEV_ACCESS_SCOPE.md"


def watch_paths(text: str) -> list[str]:
    rows = text.splitlines()
    try:
        start = rows.index("x-watch-path-coolify:") + 1
    except ValueError:
        raise ValueError("missing native x-watch-path-coolify mapping") from None
    watched: list[str] = []
    decoder = json.JSONDecoder()
    for line in rows[start:]:
        if line and not line[0].isspace() and not line.startswith("#"):
            break
        if line.startswith("  - "):
            raw = line[4:].strip()
            name, end = decoder.raw_decode(raw)
            remaining = raw[end:].strip()
            if not isinstance(name, str) or (remaining and not remaining.startswith("#")):
                raise ValueError(f"invalid watch item: {line}")
            watched.append(name)
    return watched


def control_panel_upstream_errors() -> list[str]:
    """Require the fixed proxy targets used by the canonical owner Compose files."""
    path = ROOT / "services/gateway/src/bridge/thin_gateway.py"
    try:
        tree = ast.parse(path.read_text())
    except (OSError, SyntaxError):
        return ["gateway: fixed Control Panel upstream source cannot be parsed"]
    configured = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
    }
    expected = {
        "_API_UPSTREAM": "http://briareus-control-panel-api:8000",
        "_PANEL_UPSTREAM": "http://briareus-control-panel-ui:8080",
    }
    errors = [
        f"gateway: {name} must match canonical target {target}"
        for name, target in expected.items()
        if configured.get(name) != target
    ]
    if any(
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and any(old in node.value for old in ("briareus-admin-api", "briareus-admin-ui"))
        for node in ast.walk(tree)
    ):
        errors.append("gateway: retired Control Panel DNS remains in target/host literals")
    return errors


def startup_boundary_errors(folder: str, portable: str) -> list[str]:
    """Keep cross-application startup and Core secrets out of execution Compose.

    A physical Coolify Application is a separate Compose project. Declaring
    another application's service in depends_on cannot synchronize startup.
    Never confuse a statically validated topology with runtime/readiness proof.
    """
    errors: list[str] = []
    if folder == "services/external":
        # Existing vendor stack is the sole current shared Compose unit.
        # Rauthy must wait for the reconciled owner DB, not PG TCP alone.
        rauthy = portable.partition("  briareus-rauthy:")[2]
        if (
            not rauthy
            or re.search(
                (
                    r"(?m)^    depends_on:\n      briareus-postgres:"
                    r"\n        condition: service_healthy$"
                ),
                rauthy,
            )
            is None
        ):
            errors.append("data: Rauthy must depend on same-stack Postgres readiness")
        return errors
    if re.search(r"(?m)^    depends_on:\s*$", portable):
        errors.append(
            folder + ": independent Coolify app cannot order external apps via depends_on"
        )
    if folder == "services/gateway" or folder.startswith("hands/"):
        # This is not yet physical network isolation: these applications
        # currently share briareus-net. Protect the Core secrets meanwhile.
        forbidden = re.findall(
            r"(?m)^      (POSTGRES_(?:HOST|DB|USER|PASSWORD)|RAUTHY_ADMIN_API_KEY|"
            r"OIDC_SESSION_VALKEY_PASSWORD):",
            portable,
        )
        if forbidden:
            errors.append(folder + ": execution app must not receive Core credentials")
    return errors


def bun_image_config_errors(folder: str, path: Path, dockerfile: str) -> list[str]:
    """Check local Vite config imports actually bundled into the UI image.

    An ordinary repository-root Vite build sees files that a restrictive
    Docker COPY + Dockerfile.dockerignore might omit. This checks the exact
    known Config relative import only when the committed vite.config uses it.
    It is not an image-build or TypeScript acceptance substitute.
    """
    if folder != "services/ui":
        return []
    try:
        config = (path / "vite.config.ts").read_text()
    except OSError:
        return ["control-panel-ui: Vite config missing from tracked source"]
    if re.search(r"from\s+['\"]\./local-http-proxy['\"]", config) is None:
        return []
    errors: list[str] = []
    if not (path / "local-http-proxy.ts").is_file():
        errors.append("control-panel-ui: required relative Vite config module absent")
    if "COPY services/ui/local-http-proxy.ts" not in dockerfile:
        errors.append("control-panel-ui: Dockerfile omits local Vite config dependency")
    ignore = path / "Dockerfile.dockerignore"
    if ignore.is_file():
        lines = [line.strip() for line in ignore.read_text().splitlines()]
        if "**" in lines and "!services/ui/local-http-proxy.ts" not in lines:
            errors.append("control-panel-ui: Dockerfile.dockerignore excludes Vite module")
    return errors


def owner_image_migration_errors(
    folder: str, path: Path, dockerfile: str, *, source_root: Path | None = None
) -> list[str]:
    """Fail closed if a service image omits reviewed Alembic history.

    Git source and owner_config() alone do not prove that Docker COPY and
    a restrictive Dockerfile.dockerignore include all migration revisions.
    """
    owner_by_folder = {
        "services/authorization": "access",
        "services/platform": "platform",
        "services/resources": "resources",
    }
    owner = owner_by_folder.get(folder)
    if owner is None:
        return []
    root = ROOT if source_root is None else source_root
    try:
        chain = reviewed_chain((root / "services/common/owner_migrations.py").read_text(), owner)
    except (OSError, TypeError, ValueError, SyntaxError, MemoryError):
        return [folder + ": reviewed owner migration graph missing or invalid"]
    try:
        history = MigrationHistory(
            tuple(
                migration_revision(filename.name, filename.read_text())
                for filename in sorted((path / "migrations/versions").glob("*.py"))
                if filename.name != "__init__.py"
            )
        )
    except (OSError, SyntaxError, TypeError, ValueError, MemoryError):
        return [folder + ": owner migration source cannot be parsed safely"]
    ignore = path / "Dockerfile.dockerignore"
    ignore_lines = (
        [line.strip() for line in ignore.read_text().splitlines()] if ignore.is_file() else []
    )
    return history.image_errors(folder, owner, chain, dockerfile, ignore_lines)


def saved_coolify_errors(
    snapshot: object,
    plan: object,
    *,
    targets: frozenset[str] | None = None,
) -> list[str]:
    """Assess saved exact-UUID metadata without querying external resources."""
    return saved_snapshot_errors(snapshot, plan, targets=targets)


def _previous_owner_assessment(
    binding: str, revision: str, targets: frozenset[str] | None
) -> tuple[str, ...]:
    from check_owner_schema_compat import inspect_owner

    owner, sep, previous = binding.partition("=")
    if not sep or owner not in {"platform", "resources", "authorization"}:
        return ("owner migration gate: invalid scoped owner=SHA binding",)
    if targets is not None and owner not in targets:
        return (owner + ": previous SHA specified for an unselected owner",)
    try:
        assessed = inspect_owner(ROOT, owner=owner, previous=previous, candidate=revision)
    except (ValueError, OSError, subprocess.SubprocessError):
        return (owner + ": owner schema history metadata unavailable",)
    status = assessed.state
    print("OWNER_MIGRATION_SOURCE_GATE", owner, status)
    if status == "SOURCE_COMPATIBLE":
        return ()
    return (
        owner
        + ": prior deployed migration history is "
        + ("incompatible" if status == "SOURCE_INCOMPATIBLE" else "unverified"),
    )


def _previous_owner_errors(
    bindings: tuple[str, ...], targets: frozenset[str] | None
) -> tuple[str, ...]:
    if not bindings:
        return ()
    # Inspect source at the exact previously deployed revision, never a live DB.
    proposed = subprocess.run(  # noqa: S603 -- fixed local Git read, argv only
        [_executable("git"), "-C", str(ROOT), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
        timeout=12,
    )
    revision = proposed.stdout.strip()
    if proposed.returncode or not re.fullmatch(r"[0-9a-f]{40}", revision):
        return ("owner migration gate: candidate Git revision unavailable",)
    return tuple(
        error
        for binding in bindings
        for error in _previous_owner_assessment(binding, revision, targets)
    )


def _saved_snapshot_file_errors(
    path: Path, plan: ReleasePlan, targets: frozenset[str] | None
) -> tuple[str, ...]:
    errors: tuple[str, ...]
    try:
        if path.stat().st_size > 131072:
            raise ValueError("oversized read-only metadata snapshot")
        snapshot = decode_snapshot(path.read_text())
    except (OSError, ValueError):
        errors = ("Coolify snapshot: unreadable or invalid JSON metadata",)
    else:
        errors = tuple(saved_coolify_errors(snapshot, plan.snapshot_expectation(), targets=targets))
    print("COOLIFY_SAVED_CONFIG_GATE", "PASS" if not errors else "FAIL", f"errors={len(errors)}")
    return errors


def _candidate_source_errors(unit: ReleaseCandidate, path: Path) -> tuple[str, ...]:
    required = ("Dockerfile", "docker-compose.yaml", "docker-compose.coolify.yaml")
    names = (*required, "pyproject.toml", "uv.lock", "package.json", "bun.lock")
    files = frozenset(name for name in names if (path / name).is_file())
    errors = [unit.slug + f": missing {name}" for name in required if name not in files]
    if errors:
        return tuple(errors)
    errors.extend(unit.definition_errors())
    manifest = (path / "docker-compose.coolify.yaml").read_text()
    portable = (path / "docker-compose.yaml").read_text()
    dockerfile = (path / "Dockerfile").read_text()
    errors.extend(startup_boundary_errors(unit.folder, portable))
    errors.extend(bun_image_config_errors(unit.folder, path, dockerfile))
    errors.extend(owner_image_migration_errors(unit.folder, path, dockerfile))
    try:
        errors.extend(unit.watch_errors(tuple(watch_paths(manifest))))
    except ValueError as error:
        errors.append(unit.slug + f": watch parsing failed: {error}")
    errors.extend(unit.packaging_errors(portable=portable, dockerfile=dockerfile, files=files))
    return tuple(errors)


def _candidate_tool_errors(
    unit: ReleaseCandidate, path: Path, *, compose: bool, uv_locks: bool
) -> tuple[str, ...]:
    errors: list[str] = []
    if uv_locks and unit.toolchain == "python":
        result = subprocess.run(  # noqa: S603 -- fixed lock check, reviewed manifest path, argv only
            [_executable("uv"), "lock", "--check", "--project", unit.folder],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            errors.append(
                unit.slug + ": uv lock mismatch: " + (result.stderr or result.stdout)[-340:]
            )
    if compose:
        result = subprocess.run(  # noqa: S603 -- fixed config check, reviewed source path, argv only
            [
                _executable("docker"),
                "compose",
                "--project-directory",
                str(path),
                "-f",
                str(path / "docker-compose.coolify.yaml"),
                "config",
                "--no-interpolate",
                "--quiet",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            errors.append(
                unit.slug
                + ": Docker Compose config failed: "
                + (result.stderr or result.stdout)[-500:]
            )
    return tuple(errors)


def _executable(name: Literal["git", "uv", "docker"]) -> str:
    executable = shutil.which(name)
    if executable is None:
        raise FileNotFoundError("required source inspection tool is unavailable: " + name)
    return str(Path(executable).resolve())


def _candidate_errors(unit: ReleaseCandidate, *, compose: bool, uv_locks: bool) -> tuple[str, ...]:
    path = ROOT / unit.folder
    errors = _candidate_source_errors(unit, path)
    required = ("Dockerfile", "docker-compose.yaml", "docker-compose.coolify.yaml")
    if not all((path / name).is_file() for name in required):
        return errors
    errors += _candidate_tool_errors(unit, path, compose=compose, uv_locks=uv_locks)
    print("CHECKED", unit.slug, unit.folder)
    return errors


def _print_selection(plan: ReleasePlan, targets: frozenset[str] | None) -> None:
    if targets is None:
        print(f"Flat migration source candidates={len(plan.candidates)}, held={len(plan.held)}")
    else:
        print(f"Development target-only source candidates={len(targets)}, held=0")
        print("PARTIAL_DEV_MODULE_GATE: not a 13-app or Product acceptance")


def _finish(errors: list[str]) -> int:
    for error in errors:
        print("ERROR", error, file=sys.stderr)
    print("BATCH_SOURCE_GATE", "PASS" if not errors else "FAIL", f"errors={len(errors)}")
    return int(bool(errors))


def run(
    *,
    compose: bool,
    uv_locks: bool,
    coolify_snapshot: Path | None = None,
    targets: frozenset[str] | None = None,
    previous_deployed_owners: tuple[str, ...] = (),
) -> int:
    plan = decode_release_plan(MANIFEST.read_text())
    scope_uuids = frozenset(
        ApplicationIdentity(slug, uuid)
        for slug, uuid in re.findall(
            r"\| ([a-z][\w-]*) \| [^|]+ \| ([a-z0-9]{24}) \|", SCOPE.read_text()
        )
    )
    errors = list(plan.scope_errors(scope_uuids))
    if not plan.accepts_targets(targets):
        errors.append("target gate accepts only named approved candidate modules")
        return _finish(errors)
    if targets is None or "gateway" in targets:
        errors.extend(control_panel_upstream_errors())
    errors.extend(_previous_owner_errors(previous_deployed_owners, targets))
    if coolify_snapshot is not None:
        errors.extend(_saved_snapshot_file_errors(coolify_snapshot, plan, targets))
    _print_selection(plan, targets)
    for unit in plan.candidates:
        if targets is None or unit.slug in targets:
            errors.extend(_candidate_errors(unit, compose=compose, uv_locks=uv_locks))
    if targets is None:
        for item in plan.held:
            errors.extend(item.errors())
            print("HELD", item.slug, item.reason)
    return _finish(errors)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--compose", action="store_true", help="validate every Compose input with Docker Compose"
    )
    parser.add_argument(
        "--uv-locks", action="store_true", help="verify all Python package lockfiles"
    )
    parser.add_argument(
        "--coolify-snapshot",
        type=Path,
        help="optional read-only exact-UUID saved app metadata (fresh <= 1 hour)",
    )
    parser.add_argument(
        "--target",
        action="append",
        default=[],
        help="repeatable candidate slug for independent Development module checks",
    )
    parser.add_argument(
        "--previous-deployed-owner",
        action="append",
        default=[],
        metavar="OWNER=SHA",
        help="fail-closed schema history comparison with last deployed Dev SHA",
    )
    args = parser.parse_args()
    raise SystemExit(
        run(
            compose=args.compose,
            uv_locks=args.uv_locks,
            coolify_snapshot=args.coolify_snapshot,
            targets=frozenset(args.target) if args.target else None,
            previous_deployed_owners=tuple(args.previous_deployed_owner),
        )
    )
