"""Validate relative Markdown links against the Git index or working tree."""

from __future__ import annotations

import argparse
import posixpath
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)]+)\)")
REQUIRED = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/core/README.md",
    "docs/infrastructure/README.md",
    "docs/hands/README.md",
    "docs/shared/README.md",
    "docs/operations/README.md",
)


def git(*args: str) -> bytes:
    executable = shutil.which("git")
    if executable is None:
        raise ValueError("Git executable is required for documentation checks")
    return subprocess.check_output(  # noqa: S603 -- fixed Git operation; args are separate argv
        [executable, "-C", str(ROOT), *args]
    )


def inventory(*, staged: bool) -> set[str]:
    arguments = ("ls-files", "-z") if staged else (
        "ls-files", "--cached", "--others", "--exclude-standard", "-z"
    )
    return {
        path.decode("utf-8")
        for path in git(*arguments).split(b"\0")
        if path
    }


def source_text(name: str, *, staged: bool) -> str:
    if staged:
        return git("show", f":{name}").decode("utf-8")
    return (ROOT / name).read_text(encoding="utf-8")


def links(text: str) -> list[tuple[int, str]]:
    found: list[tuple[int, str]] = []
    fenced = False
    for number, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("\x60\x60\x60", "~~~")):
            fenced = not fenced
        elif not fenced:
            found.extend((number, match.group(1)) for match in LINK.finditer(line))
    return found


def missing_link(source: str, target: str, paths: set[str]) -> bool:
    url = target.split(" ", maxsplit=1)[0].strip("<>")
    if not url or url.startswith(("https:", "http:", "mailto:", "/", "#", "data:")):
        return False
    relative = unquote(url.partition("#")[0])
    if not relative:
        return False
    location = posixpath.normpath(posixpath.join(posixpath.dirname(source), relative))
    return location not in paths and not any(path.startswith(location + "/") for path in paths)


def check(staged: bool) -> int:
    paths = inventory(staged=staged)
    failures = [
        f"missing documentation entrypoint: {path}"
        for path in REQUIRED
        if path not in paths
    ]
    files = sorted(path for path in paths if path.endswith(".md"))
    for path in files:
        for line_number, target in links(source_text(path, staged=staged)):
            if missing_link(path, target, paths):
                failures.append(f"{path}:{line_number}: missing {target}")
    for failure in failures:
        print(f"DOCUMENTATION ERROR: {failure}")
    if failures:
        return 1
    print(f"Documentation links OK: {len(files)} files ({'index' if staged else 'worktree'}).")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged", action="store_true", help="check proposed Git index")
    args = parser.parse_args()
    return check(staged=args.staged)


if __name__ == "__main__":
    raise SystemExit(main())
