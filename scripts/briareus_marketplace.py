#!/usr/bin/env python3
"""Generate one Briareus V1 project skill, independently of AI Agent Workflow."""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path("plugins/briareus-v1")
SKILL = PACKAGE / "skills/briareus-v1"
MANIFEST = Path(".agents/plugins/marketplace.json")
DEPRECATED = (
    "briareus-server-workflows",
    "briareus-github-workflows",
    "briareus-gitlab-workflows",
    "briareus-coolify-workflows",
)
LINK = re.compile(r"\[[^\]]+\]\(([^)\s]+)\)")


def _json(data: object) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _source_files() -> dict[str, bytes]:
    paths = {
        Path("AGENTS.md"),
        Path("README.md"),
        Path("deploy/services.json"),
        *[
            p.relative_to(ROOT)
            for p in (ROOT / "docs").rglob("*.md")
            if p.is_file() and p.relative_to(ROOT).parts[1] not in {"history", "refactoring"}
        ],
    }
    catalog = json.loads((ROOT / "deploy/services.json").read_text(encoding="utf-8"))
    for owner in catalog["services"]:
        paths.add(Path(owner["directory"]) / "README.md")
    result: dict[str, bytes] = {}
    for path in sorted(paths):
        absolute = ROOT / path
        if absolute.is_symlink() or not absolute.is_file():
            raise ValueError(f"Missing or unsafe Briareus source: {path}")
        data = absolute.read_bytes()
        data.decode("utf-8")
        if len(data) > 256 * 1024:
            raise ValueError(f"Oversized Briareus reference: {path}")
        result[path.as_posix()] = data
    return result


def _link_target(path: str, raw: str, bundled: set[str]) -> str:
    if raw.startswith(("http:", "https:", "#", "mailto:", "data:", "/")):
        return raw
    target, sep, fragment = raw.partition("#")
    if not target:
        return raw
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(target)))
    if resolved.startswith("../") or resolved == "..":
        raise ValueError("Reference link escaped source root")
    if resolved in bundled or resolved.rstrip("/") + "/README.md" in bundled:
        return raw
    result = f"https://github.com/KobaProduction/Briareus/blob/v1/{resolved}"
    return result + ("#" + fragment if sep else "")


def _package_reference(path: str, data: bytes, bundled: set[str]) -> bytes:
    if not path.endswith(".md"):
        return data
    text = data.decode("utf-8")
    for match in reversed(list(LINK.finditer(text))):
        start, end = match.span(1)
        text = text[:start] + _link_target(path, match.group(1), bundled) + text[end:]
    return text.encode("utf-8")


def generated_files() -> dict[Path, bytes]:
    original = _source_files()
    bundled = set(original)
    packaged = {path: _package_reference(path, data, bundled) for path, data in original.items()}
    marketplace = {
        "name": "briareus-v1",
        "interface": {"displayName": "Briareus V1"},
        "plugins": [
            {
                "name": "briareus-v1",
                "source": {"source": "local", "path": "./plugins/briareus-v1"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        ],
    }
    interface = {
        "displayName": "Briareus V1",
        "shortDescription": "Platform architecture, MCP and safe operations",
        "longDescription": (
            "One task-routed Briareus V1 Skill containing project-specific docs "
            "and service ownership boundaries."
        ),
        "developerName": "Briareus",
        "category": "Productivity",
        "capabilities": ["Read"],
    }
    plugin = {
        "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
        "name": "briareus-v1",
        "version": "1.0.0",
        "description": "Briareus V1 architecture, services, MCP Hands and operations",
        "author": {"name": "Briareus"},
        "repository": "https://github.com/KobaProduction/Briareus",
        "skills": "./skills/",
        "extensions": {"com.openai": {"interface": interface}},
    }
    skill = (
        b"---\nname: briareus-v1\n"
        b'description: "Work on the Briareus V1 platform, MCP Hands, Gateway, '
        b'Control Panel, Coolify, runtime, Git policies, and tests."\n'
        b"""---

# Briareus V1 project workflows

This skill contains Briareus-specific project context; it does not replace
universal engineering Skills, grant MCP permissions or describe the separate V2 architecture.

Before Briareus source work, read references/AGENTS.md, references/README.md and
references/docs/core/runtime.md in full. Then route to the relevant owner documentation:

- MCP server/files/terminal: references/docs/hands/server.md
- GitHub/GitLab: references/docs/hands/source-control.md
- Analysis, browser, telemetry: references/docs/hands/README.md
- Gateway, panel, dependencies: references/docs/services/README.md
- Coolify/build/config: references/docs/operations/README.md
- Testing: references/docs/operations/testing.md
- Git/worktrees: references/docs/operations/git-and-worktrees.md

The service catalogue is references/deploy/services.json. Each selected service's
README is under references/services. Read every selected mandatory owner document
completely. Check current Git branch, live resources and permissions before
mutations. Preserve external secrets, persistent volumes and the V1/V2 boundary;
no changes to stopped services without approval. Other task-specific engineering
workflows belong to the separate AI Agent Workflow plugin.
"""
    )
    files = {
        MANIFEST: _json(marketplace),
        PACKAGE / "plugin.json": _json(plugin),
        PACKAGE / ".codex-plugin/plugin.json": _json(
            {
                "name": "briareus-v1",
                "version": "1.0.0",
                "description": plugin["description"],
                "skills": "./skills/",
                "interface": interface,
            }
        ),
        SKILL / "SKILL.md": skill,
    }
    files.update({SKILL / "references" / path: data for path, data in packaged.items()})
    files[SKILL / "SOURCE.json"] = _json(
        {
            "repository": "KobaProduction/Briareus",
            "branch": "v1",
            "files": {path: hashlib.sha256(data).hexdigest() for path, data in packaged.items()},
            "original_files": {
                path: hashlib.sha256(data).hexdigest() for path, data in original.items()
            },
        }
    )
    return files


def _owner_files(directory: Path) -> set[Path]:
    if directory.is_symlink():
        raise ValueError(f"Symlink in managed plugin: {directory}")
    result: set[Path] = set()
    if directory.is_dir():
        for file in directory.rglob("*"):
            if file.is_symlink():
                raise ValueError(f"Symlink in managed plugin: {file}")
            if file.is_file():
                result.add(file.relative_to(ROOT))
    return result


def _managed_files() -> set[Path]:
    result: set[Path] = set()
    for name in (*DEPRECATED, "briareus-v1"):
        result.update(_owner_files(ROOT / "plugins" / name))
    if (ROOT / MANIFEST).is_file():
        result.add(MANIFEST)
    return result


def _remove_empty_deprecated_dirs() -> None:
    for name in DEPRECATED:
        directory = ROOT / "plugins" / name
        if not directory.is_dir():
            continue
        for child in sorted(directory.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            if child.is_dir():
                child.rmdir()
        directory.rmdir()


def _write_changes(stale: list[Path], changed: list[Path], expected: dict[Path, bytes]) -> None:
    for path in stale:
        (ROOT / path).unlink()
    _remove_empty_deprecated_dirs()
    for path in changed:
        destination = ROOT / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(expected[path])


def update(*, check: bool) -> tuple[int, int]:
    expected = generated_files()
    old = _managed_files()
    changed = sorted(
        path
        for path, data in expected.items()
        if not (ROOT / path).is_file() or (ROOT / path).read_bytes() != data
    )
    stale = sorted(old - expected.keys())
    if check and (changed or stale):
        raise ValueError(f"Marketplace drift: {len(changed)} changed, {len(stale)} stale")
    if not check:
        _write_changes(stale, changed, expected)
    return len(changed), len(stale)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    changed, stale = update(check=args.check)
    print(
        json.dumps(
            {"plugins": 1, "skills": 1, "changed": changed, "stale": stale, "check": args.check}
        )
    )


if __name__ == "__main__":
    main()
