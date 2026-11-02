"""Git-aware selection without stashing or modifying the index."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GENERATED = ("_pb2.py", "_pb2_grpc.py")


def git(*args: str) -> list[str]:
    raw = subprocess.check_output(  # noqa: S603 -- fixed Git subcommands, refs are argv, never shell
        [shutil.which("git") or "git", *args], cwd=ROOT
    )
    return [value for value in raw.decode().split("\0") if value]


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Strict local lint, types, architecture and tests")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--all", action="store_true")
    scope.add_argument("--staged", action="store_true")
    scope.add_argument("--push", action="store_true")
    scope.add_argument("--base", help="Check changes from this ref to HEAD")
    parser.add_argument("--checks", choices=["all", "lint", "tests"], default="all")
    return parser.parse_args()


def push_paths() -> list[str]:
    paths: set[str] = set()
    for line in sys.stdin:
        _, local, _, remote = line.split()
        if set(local) == {"0"}:
            continue
        head = git("rev-parse", "HEAD")[0].strip()
        if local != head:
            raise ValueError(
                "Check out the outgoing commit before pushing: hooks must test that exact revision."
            )
        if set(remote) == {"0"}:
            return git("ls-files", "-z")
        paths.update(git("diff", "--name-only", "--diff-filter=ACMRD", "-z", remote, local))
    return sorted(paths)


def selected(args: argparse.Namespace) -> list[str]:
    if (args.staged or args.push) and git("diff", "--name-only", "-z"):
        raise ValueError(
            "Stage or stash tracked worktree changes first: hooks must check committed content."
        )
    if args.all:
        paths = git("ls-files", "--cached", "--others", "--exclude-standard", "-z")
    elif args.staged:
        paths = git("diff", "--cached", "--name-only", "--diff-filter=ACMRD", "-z")
    elif args.push:
        paths = push_paths()
        if paths and set(paths) == set(git("ls-files", "-z")):
            args.all = True
    elif args.base:
        paths = git("diff", "--name-only", "--diff-filter=ACMRD", "-z", args.base, "HEAD")
    else:
        paths = git("diff", "HEAD", "--name-only", "--diff-filter=ACMRD", "-z")
        paths += git("ls-files", "--others", "--exclude-standard", "-z")
    return sorted({p for p in paths if not p.endswith(GENERATED)})


def is_test(path: str) -> bool:
    value = Path(path)
    return (
        "tests" in value.parts or value.name.startswith("test_") or value.name.endswith("_test.py")
    )


def owner(path: str) -> Path:
    """Find the dependency project used to run uv and tests."""
    location = (ROOT / path).resolve()
    location.relative_to(ROOT)
    if location == ROOT:
        return ROOT
    for parent in location.parents:
        if parent == ROOT:
            break
        if (parent / "pyproject.toml").exists():
            return parent
    return ROOT


def source_owner(path: str) -> Path:
    """Keep flat source owners isolated even when they share a dependency project."""
    location = (ROOT / path).resolve()
    relative = location.relative_to(ROOT)
    if len(relative.parts) >= 3 and relative.parts[0] in {"services", "hands", "shared"}:
        base = ROOT.joinpath(*relative.parts[:2])
        project = owner(path)
        return project if project.is_relative_to(base) else base
    return owner(path)
