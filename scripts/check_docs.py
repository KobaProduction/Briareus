#!/usr/bin/env python3
"""Validate current V1 documentation links and source-catalog ownership."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
CORE = frozenset({"control-panel-ui", "control-panel-api", "gateway", "dependencies"})
DOCS = (
    "AGENTS.md",
    "README.md",
    "docs/README.md",
    "docs/core/README.md",
    "docs/core/runtime.md",
    "docs/services/README.md",
    "docs/hands/README.md",
    "docs/operations/README.md",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
SERVICE_NAME = re.compile(r"\x60([a-z][a-z0-9-]*)\x60")


def markdown_files() -> list[Path]:
    tracked = subprocess.check_output(
        [
            "git",
            "-C",
            str(ROOT),
            "ls-files",
            "-z",
            "--cached",
            "--others",
            "--exclude-standard",
            "--",
            "*.md",
        ]
    )
    return sorted(
        ROOT / path.decode("utf-8")
        for path in tracked.split(b"\0")
        if path.endswith(b".md") and (ROOT / path.decode("utf-8")).is_file()
    )


def markdown_links(path: Path) -> list[tuple[int, str]]:
    matches: list[tuple[int, str]] = []
    fenced = False
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.lstrip().startswith(("\x60\x60\x60", "~~~")):
            fenced = not fenced
        elif not fenced:
            matches.extend((line_number, item.group(1)) for item in LINK.finditer(line))
    return matches


def missing_target(path: Path, raw_target: str) -> str | None:
    target = raw_target.split(" ", maxsplit=1)[0].strip("<>")
    if not target or target.startswith(("#", "/", "https:", "http:", "mailto:", "data:")):
        return None
    location = unquote(target.partition("#")[0])
    if location and not (path.parent / location).exists():
        return target
    return None


def broken_links(paths: list[Path]) -> list[str]:
    failures: list[str] = []
    for path in paths:
        for line_number, raw_target in markdown_links(path):
            target = missing_target(path, raw_target)
            if target:
                failures.append(f"{path.relative_to(ROOT)}:{line_number}: missing {target}")
    return failures


def catalog_failures() -> list[str]:
    manifest = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    names = [item["name"] for item in manifest["services"]]
    hands = set(names) - CORE
    failures: list[str] = []
    if len(names) != len(set(names)):
        failures.append("deploy/services.json: repeated resource names")
    if not CORE.issubset(names):
        failures.append("deploy/services.json: missing core service")
    if len(names) != 15 or len(hands) != 11:
        failures.append(
            f"catalog count changed to {len(names)} resources/{len(hands)} Hands; "
            "update the catalog contract and all owner documentation"
        )
    text = (ROOT / "docs/hands/README.md").read_text(encoding="utf-8")
    present = set(SERVICE_NAME.findall(text))
    failures.extend(
        f"docs/hands/README.md: missing Hand {name}"
        for name in sorted(hands)
        if name not in present
    )
    return failures


def main() -> int:
    failures = [
        *(f"missing required entrypoint: {path}" for path in DOCS if not (ROOT / path).is_file()),
        *broken_links(markdown_files()),
        *catalog_failures(),
    ]
    for failure in failures:
        print(f"DOCUMENTATION ERROR: {failure}")
    if failures:
        return 1
    print(
        "Documentation OK: all relative Markdown links resolve; "
        "15 source resources, 4 core services and 11 documented Hands."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
