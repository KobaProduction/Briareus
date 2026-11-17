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
        "description": "Using Briareus V1 MCP tools and maintaining the V1 platform",
        "author": {"name": "Briareus"},
        "repository": "https://github.com/KobaProduction/Briareus",
        "skills": "./skills/",
        "extensions": {"com.openai": {"interface": interface}},
    }
    skill = b"""---
name: briareus-v1
description: "Use Briareus V1 MCP Hands or maintain the V1 platform and services."
---

# Briareus MCP usage and V1 platform

Use this Skill when working through any Briareus V1 MCP connection, even for
other projects. This is a Briareus-specific integration guide, not a universal
engineering workflow. AI Agent Workflow Skills, when installed, supply generic
Git, testing, development and deployment methods independently.

## For ordinary MCP tool use

1. Identify which Briareus Hand is relevant and inspect its available
   tools, descriptions, schemas, accounts, and effective permissions.
2. Load only the matching Hand's guidance. Prefer that Hand's local MCP
   Skill if supported, otherwise call its read_project_workflow tool.
   The source-specific reference maps in this package can also be read:
   - Server/files/terminal: references/docs/hands/server.md
   - GitHub and GitLab: references/docs/hands/source-control.md
   - Browser: references/docs/hands/browser.md
   - Analyzer/Ghidra/radare2: references/docs/hands/analysis.md
   - Coolify and SigNoz: references/docs/hands/telemetry.md
3. Read required guidance completely before dependent actions. Confirm
   credentials, working directory and actual remote/target state.
4. Respect user approval, tool boundaries, protected branches and secret
   handling. A visible tool does not grant its permission. A submitted
   deployment is not proof of a healthy resource.
5. Do not require a checkout of the Briareus repository or the independent
   AI Agent Workflow repository for ordinary MCP calls.

## For modifying Briareus V1 itself

Read references/AGENTS.md, references/README.md and
references/docs/core/runtime.md in full. Follow their owner routing.
Use references/deploy/services.json for the service catalogue, and the
selected reference under references/services/ for the service owner.
Operations and validation start from references/docs/operations/README.md;
Git and worktrees from references/docs/operations/git-and-worktrees.md.
Verify the active v1 branch and distinct V2 policies before making changes.

The project Skill and server-native Hand Skills are complementary; the
marketplace does not install or grant MCP connections. Universal engineering
Skills remain in their own AI Agent Workflow marketplace.
"""
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
