"""Run all gates, even when an earlier gate fails. No source rewriting."""

from __future__ import annotations

import sys
import time
from contextlib import redirect_stdout

import architecture
import contracts
from runner import REPORTS, Result, frontend, python_lint, python_types, summary, tests
from selection import ROOT, arguments, selected


def contracts_result(paths: list[str]) -> Result:
    REPORTS.mkdir(parents=True, exist_ok=True)
    log = REPORTS / "python-contracts.log"
    start = time.monotonic()
    with log.open("w", encoding="utf-8") as output, redirect_stdout(output):
        status = contracts.check(paths)
        status |= architecture.check(paths)
    print(
        f"Python cognitive/result contracts: {'FAIL' if status else 'PASS'} "
        f"({log.relative_to(ROOT)})",
        flush=True,
    )
    return Result(
        "python-contracts", status, round(time.monotonic() - start, 2), str(log.relative_to(ROOT))
    )


def lint(paths: list[str], full: bool) -> list[Result]:
    python = [path for path in paths if path.endswith(".py") and (ROOT / path).is_file()]
    ui = [path for path in paths if path.startswith("services/ui/") and (ROOT / path).is_file()]
    results: list[Result] = []
    if python:
        results.extend(python_lint(python))
        results.append(contracts_result(python))
        results.extend(python_types(python))
    results.extend(frontend(ui, full))
    return results


def main() -> int:
    args = arguments()
    try:
        paths = selected(args)
        config_changed = any(
            path in {"pyproject.toml", "services/ui/biome.json", "services/ui/steiger.config.ts"}
            or path.startswith("scripts/quality")
            for path in paths
        )
        if config_changed and not args.all:
            args.all = True
            paths = selected(args)
        print(
            f"Selected {len(paths)} files ({'full' if args.all else 'affected'} mode).", flush=True
        )
        results = lint(paths, args.all) if args.checks != "tests" else []
        if args.checks != "lint":
            results.extend(tests(paths, args.all))
        return summary(results, args.checks)
    except (ValueError, OSError) as error:
        print(f"Quality gate could not run: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
