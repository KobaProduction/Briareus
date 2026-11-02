#!/usr/bin/env python3
"""Offline, generated Coolify Watch Paths impact from the ONLY source x-watch-path-coolify.

No second watch registry/list; no remote access, no tests or mock service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from watch_policy import ImpactError, ImpactReport, WatchPattern, WatchPlan, calculate_impact
from watch_sources import WatchSource, representative

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent if (ROOT.parent / "services").is_dir() else ROOT.parents[3] / "repo"


def watch_list(module: str) -> list[str]:
    return [pattern.value for pattern in WatchSource(ROOT, REPO).plan(module).patterns]


def matched(pattern: str, name: str) -> bool:
    return WatchPattern(pattern).matches(name)


def generated_impact(changed: list[str]) -> ImpactReport:
    return calculate_impact(WatchSource(ROOT, REPO).plans(), changed)


def discovered_representatives(source_root: Path) -> list[str]:
    source = WatchSource(ROOT, source_root)
    representatives = [
        name
        for plan in source.plans()
        for pattern in plan.patterns
        if (name := representative(source, pattern)) is not None
    ]
    representatives += [
        "deploy/README.md",
        "deploy/SHA256SUMS",
        "docs/architecture/storage-ownership-orchestrator-review.md",
    ]
    return sorted(set(representatives))


def _watch_exists(
    source: WatchSource, module: str, pattern: str, allow_pending: bool
) -> str | None:
    if pattern.endswith("/**"):
        root = source.repository / pattern[:-3]
        if not root.is_dir():
            if allow_pending and pattern.startswith("scripts/alembic_owners/"):
                return f"{module}: {pattern} (A11 NOT FAN-IN)"
            raise ImpactError(f"{module}: nonexistent directory watch {pattern}")
        if not any(path.is_file() for path in root.rglob("*")):
            raise ImpactError(f"{module}: empty watched directory {pattern}")
    elif not any(character in pattern for character in "*?["):
        if not source.explicit_path(pattern).is_file():
            raise ImpactError(f"{module}: nonexistent explicit watch {pattern}")
    return None


def _check_isolation(plans: tuple[WatchPlan, ...]) -> None:
    owner_apps = (
        ("identity", "identity"),
        ("access", "authorization"),
        ("platform", "platform"),
        ("resources", "resources"),
    )
    expected: list[tuple[str, tuple[str, ...]]] = [
        (f"scripts/alembic_owners/{owner}/env.py", (app,)) for owner, app in owner_apps
    ]
    expected.extend(
        (
            ("deploy/README.md", ()),
            ("services/projects/_catalog_ledger.py", ("resources",)),
            ("services/modules/files/project_files.py", ("files", "web")),
            ("admin-web-app/src/main.ts", ("admin-ui",)),
            # Every active adapter watches shared External, per owner contract.
            ("services/external/docker-compose.yaml", tuple(plan.module for plan in plans)),
        )
    )
    report = calculate_impact(plans, [path for path, _ in expected])
    for path, consumers in expected:
        actual = report.consumers(path)
        if set(actual) != set(consumers):
            raise ImpactError(f"{path}: incorrect actual import dependency impact: {actual}")


def check_coverage(source_root: Path, allow_pending: bool) -> list[str]:
    source = WatchSource(ROOT, source_root)
    plans = source.plans()
    pending = [
        diagnostic
        for plan in plans
        for pattern in plan.patterns
        if (diagnostic := _watch_exists(source, plan.module, pattern.value, allow_pending))
        is not None
    ]
    if (source_root / "scripts/alembic_greenfield/env.py").exists():
        raise ImpactError("retired global migrator unexpectedly exists in source tree")
    _check_isolation(plans)
    return pending


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changed-file",
        action="append",
        default=[],
        help="repo-relative changed file (repeatable)",
    )
    parser.add_argument(
        "--matrix",
        action="store_true",
        help="derive sample input->affected Apps from Compose watch lists",
    )
    parser.add_argument(
        "--check", action="store_true", help="static source coverage and isolation checks"
    )
    parser.add_argument(
        "--source-root",
        type=Path,
        default=REPO,
        help="source tree to check; default accepted central repo",
    )
    parser.add_argument(
        "--allow-pending-owner-source",
        action="store_true",
        help="explicitly mark missing A11 revision paths as UNVERIFIED",
    )
    args = parser.parse_args()
    if args.check:
        missing = check_coverage(args.source_root, args.allow_pending_owner_source)
        if missing:
            print("WATCH_SOURCE_PENDING_A11:", "; ".join(missing))
        else:
            print("WATCH_SOURCE_COVERAGE_PASS")
    names = args.changed_file or (
        discovered_representatives(args.source_root) if args.matrix else []
    )
    if names:
        impacted = generated_impact(names)
        print(
            json.dumps(
                {entry.path: list(entry.modules) for entry in impacted.files},
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ImpactError, ValueError, OSError, KeyError) as exc:
        print(f"WATCH_ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
