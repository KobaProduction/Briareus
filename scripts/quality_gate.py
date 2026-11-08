"""Enforce bounded Python functions, strict types and affected contract checks."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

from ci_plan import plan
from complexipy import file_complexity

ROOT = Path(__file__).resolve().parents[1]


def git(*arguments: str) -> str:
    return subprocess.check_output(["git", *arguments], cwd=ROOT, text=True).strip()


def run(*arguments: str) -> None:
    subprocess.run(arguments, cwd=ROOT, check=True)


def tracked_inputs() -> list[Path]:
    names = git("ls-files", "--cached", "--others", "--exclude-standard", "-z").split("\0")
    return sorted({ROOT / name for name in names if name and (ROOT / name).is_file()})


def fingerprint() -> str:
    digest = hashlib.sha256()
    digest.update(git("ls-files", "--stage", "-z").encode())
    for path in tracked_inputs():
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def receipt_path() -> Path:
    return Path(git("rev-parse", "--absolute-git-dir")) / "briareus-quality.json"


def receipts() -> dict[str, str]:
    path = receipt_path()
    if not path.exists():
        return {}
    value: object = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        return {}
    return {str(key): str(item) for key, item in value.items()}


def cognitive(paths: list[Path]) -> None:
    failures = []
    for path in paths:
        limit = 30 if "tests" in path.relative_to(ROOT).parts else 15
        failures.extend(
            f"{path.relative_to(ROOT)}:{function.line_start}: "
            f"{function.name}: cognitive complexity {function.complexity} > {limit}"
            for function in file_complexity(str(path), no_ignore=True).functions
            if function.complexity > limit
        )
    if failures:
        raise ValueError("\n".join(failures))


def selected_paths(result: dict[str, object], key: str) -> list[str]:
    values = result[key]
    if not isinstance(values, list) or not all(isinstance(value, str) for value in values):
        raise ValueError(f"Invalid quality plan: {key}")
    return values


def static_checks(result: dict[str, object]) -> None:
    ruff = selected_paths(result, "ruff_paths")
    types = selected_paths(result, "mypy_paths")
    if ruff:
        run("uv", "run", "--frozen", "--no-env-file", "ruff", "check", *ruff)
        cognitive(python_paths(ruff))
    if types:
        run("uv", "run", "--frozen", "--no-env-file", "--group", "web", "mypy", *types)


def full_tests() -> None:
    run(sys.executable, "scripts/briareus_catalog.py", "--check")
    run(sys.executable, "scripts/briareus_dockerfiles.py", "--check")
    run(sys.executable, "scripts/briareus_coolify.py", "--check")
    run(sys.executable, "scripts/validate_locks.py")
    run(sys.executable, "scripts/validate_compose.py")
    run(sys.executable, "tests/run_briareus_contracts.py", "--all")
    run("uv", "run", "--frozen", "--no-env-file", "python",
        "services/control-panel/api/tests/integration/postgres_migrations.py")
    subprocess.run(["bun", "run", "build"], cwd=ROOT / "services/control-panel/ui", check=True)
    subprocess.run(["bun", "test"], cwd=ROOT / "services/control-panel/ui", check=True)


def hook_paths(mode: str) -> list[str]:
    if git("diff", "--name-only") or git("ls-files", "--others", "--exclude-standard"):
        raise ValueError("Stage all source changes before validation; working tree differs.")
    if mode == "staged":
        return git("diff", "--cached", "--name-only").splitlines()
    if git("status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Push validation requires a clean tracked working tree.")
    changed = []
    new_branch = False
    for line in sys.stdin:
        _, local, _, remote = line.split()
        if set(local) == {"0"}:
            continue
        if local != git("rev-parse", "HEAD"):
            raise ValueError("Check out the outgoing commit before push validation.")
        if set(remote) == {"0"}:
            new_branch = True
        else:
            changed.extend(git("diff", "--name-only", remote, local).splitlines())
    return ["pyproject.toml"] if new_branch else changed


def python_paths(selected: list[str]) -> list[Path]:
    prefixes = tuple(item.rstrip("/") + "/" for item in selected)
    return [
        path for path in tracked_inputs()
        if path.suffix == ".py" and (
            path.relative_to(ROOT).as_posix() in selected
            or path.relative_to(ROOT).as_posix().startswith(prefixes)
        )
    ]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("all", "staged", "push"), default="all")
    parser.add_argument("--all", action="store_const", const="all", dest="mode")
    parser.add_argument("--cognitive-only", nargs="*", metavar="PATH")
    parser.add_argument("--tests", action="store_true", help="Run the final complete suite once")
    args = parser.parse_args()
    if args.cognitive_only is not None:
        cognitive(python_paths(args.cognitive_only))
        return
    paths = [] if args.mode == "all" else hook_paths(args.mode)
    if args.mode != "all" and not paths:
        return
    result = plan(paths, force_full=args.mode == "all")
    before = fingerprint()
    saved = receipts()
    if saved.get("static") != before:
        static_checks(result)
        if result["full"]:
            saved["static"] = before
    if args.tests and saved.get("tests") != before:
        full_tests()
        saved["tests"] = before
    if args.mode in {"staged", "push"} and saved.get("tests") != before:
        raise ValueError("Run the final suite: uv run --group quality python "
                         "scripts/quality_gate.py --all --tests")
    if fingerprint() != before:
        raise ValueError("Source changed during validation; results were not recorded.")
    receipt_path().write_text(json.dumps(saved), encoding="utf-8")
    print("Briareus quality checks passed for the current source fingerprint.")


if __name__ == "__main__":
    main()
