#!/usr/bin/env python3
"""Build and verify Briareus's importable Codex/ChatGPT Skills marketplace.

Only fixed, reviewed Briareus Skills and allowlisted documents from an immutable
ai-agent-workflow Git commit may enter the generated plugin packages.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import posixpath
import re
import runpy
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import cast
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parents[1]
# workflow_sync.py is stdlib-only; importing its package __init__ would load
# runtime dependencies that are not available in a bare GitHub Actions runner.
_SYNC = runpy.run_path(str(ROOT / "shared/hand_runtime/src/briareus_hand_runtime/workflow_sync.py"))
REPOSITORY = cast(str, _SYNC["REPOSITORY"])
is_allowed = cast(Callable[[str, str], bool], _SYNC["is_allowed"])
mandatory_paths = cast(Callable[[str], tuple[str, ...]], _SYNC["mandatory_paths"])
router = cast(Callable[[str, str], str], _SYNC["router"])

SHA = re.compile(r"[0-9a-f]{40}\Z")
MAX_FILE = 128 * 1024
MAX_TOTAL = 16 * 1024 * 1024
PLUGIN_NAMES = ("server", "github", "gitlab", "coolify")
PROVIDER_SKILLS = {
    "server": (
        "server-project-workflow",
        "services/hands/server/src/briareus_server/skills/server-project-workflow/SKILL.md",
    ),
    "github": (
        "github-repository-workflow",
        "services/hands/svc/github/src/briareus_github/skills/github-repository-workflow/SKILL.md",
    ),
    "gitlab": (
        "gitlab-repository-workflow",
        "services/hands/svc/gitlab/src/briareus_gitlab/skills/gitlab-repository-workflow/SKILL.md",
    ),
    "coolify": (
        "coolify-deployment-workflow",
        "services/hands/infrastructure/coolify/src/briareus_coolify/skills/coolify-deployment-workflow/SKILL.md",
    ),
}
SHARED_SKILL = (
    "shared/hand_runtime/src/briareus_hand_runtime/skills/source-control-publishing/SKILL.md"
)
DESCRIPTIONS = {
    "server": "Workspace, files, terminal and safe Git checkout workflows",
    "github": "GitHub repositories, publishing and source-control coordination",
    "gitlab": "GitLab repositories, publishing and source-control coordination",
    "coolify": "Coolify deployments, services and configuration workflows",
}


def _json(data: object) -> bytes:
    return (json.dumps(data, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def _git(repo: Path, *args: str) -> bytes:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=False,
        capture_output=True,
    )
    if result.returncode:
        raise ValueError(
            f"Git refused {args[0]} in upstream checkout: "
            + result.stderr.decode("utf-8", errors="replace")[:400]
        )
    return result.stdout


def _validate_revision(checkout: Path, revision: str) -> None:
    if not SHA.fullmatch(revision):
        raise ValueError("A pinned 40-character lowercase upstream commit is required")
    actual = _git(checkout, "rev-parse", "--verify", revision + "^{commit}").strip().decode()
    if actual != revision:
        raise ValueError("Upstream commit does not resolve to the requested revision")
    _git(checkout, "merge-base", "--is-ancestor", revision, "HEAD")


def _bundle_documents(
    checkout: Path, revision: str, paths: list[str], bundle: str
) -> dict[str, bytes]:
    selected = sorted(path for path in paths if is_allowed(bundle, path))
    if len(selected) > 80:
        raise ValueError("Too many upstream files in the allowlist")
    missing = set(mandatory_paths(bundle)) - set(selected)
    if missing:
        raise ValueError(f"Missing mandatory {bundle} documents: {sorted(missing)}")
    result: dict[str, bytes] = {}
    for path in selected:
        raw = _git(checkout, "show", f"{revision}:{path}")
        if not raw or len(raw) > MAX_FILE:
            raise ValueError(f"Invalid upstream document size: {path}")
        raw.decode("utf-8")
        result[path] = raw
    return result


def upstream_documents(checkout: Path, revision: str) -> dict[str, dict[str, bytes]]:
    """Read only selected files from an immutable commit, never a mutable worktree."""
    _validate_revision(checkout, revision)
    tree = _git(checkout, "ls-tree", "-r", "--name-only", "-z", revision)
    paths = [item.decode("utf-8") for item in tree.split(bytes([0])) if item]
    bundles = {
        bundle: _bundle_documents(checkout, revision, paths, bundle)
        for bundle in ("git", "coolify")
    }
    total = sum(len(raw) for documents in bundles.values() for raw in documents.values())
    if total > MAX_TOTAL:
        raise ValueError("Combined workflow documents exceed the size limit")
    return bundles


def _link_target(path: str, link: str, available: set[str], revision: str) -> str:
    if link.startswith(("#", "/", "http:", "https:", "mailto:", "data:")):
        return link
    relative, separator, fragment = link.partition("#")
    if not relative or " " in relative:
        return link
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), unquote(relative)))
    if resolved.startswith("../") or resolved == "..":
        raise ValueError("Upstream link escapes its repository")
    if resolved in available:
        return link
    target = f"https://github.com/{REPOSITORY}/blob/{revision}/{resolved}"
    return target + ("#" + fragment if separator else "")


def _packaged_reference(path: str, raw: bytes, available: set[str], revision: str) -> bytes:
    """Redirect links outside the allowlist to the exact upstream Git revision."""
    text = raw.decode("utf-8")
    for match in reversed(list(re.finditer(r"\[[^\]]+\]\(([^)]+)\)", text))):
        start, end = match.span(1)
        target = _link_target(path, match.group(1), available, revision)
        text = text[:start] + target + text[end:]
    return text.encode("utf-8")


def _imported_skill_files(
    root: Path, bundle: str, revision: str, sources: dict[str, bytes]
) -> dict[Path, bytes]:
    name = "ai-agent-services-deployment" if bundle == "coolify" else "ai-agent-git-workflow"
    target = root / name
    available = set(sources)
    packaged = {
        path: _packaged_reference(path, raw, available, revision) for path, raw in sources.items()
    }
    files = {target / "SKILL.md": router(bundle, revision).encode("utf-8")}
    files.update({target / "references" / path: raw for path, raw in packaged.items()})
    files[target / "SOURCE.json"] = _json(
        {
            "repository": REPOSITORY,
            "revision": revision,
            "bundle": bundle,
            "files": {path: hashlib.sha256(raw).hexdigest() for path, raw in packaged.items()},
            "upstream_files": {
                path: hashlib.sha256(raw).hexdigest() for path, raw in sources.items()
            },
        }
    )
    return files


def _skill_files(
    plugin: str, revision: str, bundles: dict[str, dict[str, bytes]]
) -> dict[Path, bytes]:
    root = Path("plugins") / f"briareus-{plugin}-workflows" / "skills"
    skill_name, local = PROVIDER_SKILLS[plugin]
    result = {root / skill_name / "SKILL.md": (ROOT / local).read_bytes()}
    if plugin in {"github", "gitlab"}:
        result[root / "source-control-publishing" / "SKILL.md"] = (ROOT / SHARED_SKILL).read_bytes()
    if plugin != "server":
        bundle = "coolify" if plugin == "coolify" else "git"
        result.update(_imported_skill_files(root, bundle, revision, bundles[bundle]))
    return result


def expected_files(revision: str, bundles: dict[str, dict[str, bytes]]) -> dict[Path, bytes]:
    """Render deterministic portable + Codex-compatible plugin packages."""
    marketplace: dict[str, object] = {
        "name": "briareus-v1",
        "interface": {"displayName": "Briareus V1 Skills"},
        "plugins": [],
    }
    result: dict[Path, bytes] = {}
    entries = marketplace["plugins"]
    assert isinstance(entries, list)
    for plugin in PLUGIN_NAMES:
        name = f"briareus-{plugin}-workflows"
        root = Path("plugins") / name
        short = DESCRIPTIONS[plugin]
        entries.append(
            {
                "name": name,
                "source": {"source": "local", "path": f"./plugins/{name}"},
                "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                "category": "Productivity",
            }
        )
        result[root / "plugin.json"] = _json(
            {
                "$schema": "https://agent-plugins.org/schemas/1.0.0/plugin.schema.json",
                "name": name,
                "version": "1.0.0",
                "description": short,
                "author": {"name": "Briareus"},
                "repository": "https://github.com/KobaProduction/Briareus",
            }
        )
        result[root / ".codex-plugin" / "plugin.json"] = _json(
            {
                "name": name,
                "version": "1.0.0",
                "description": short,
                "skills": "./skills/",
                "interface": {
                    "displayName": f"Briareus V1 / {plugin.title()} Skills",
                    "shortDescription": short,
                    "longDescription": (
                        "Native Skills for Briareus V1. Works with separately "
                        "connected Briareus MCP tools and respects their permissions."
                    ),
                    "developerName": "Briareus",
                    "category": "Productivity",
                    "capabilities": ["Read"],
                },
            }
        )
        result.update(_skill_files(plugin, revision, bundles))
    result[Path(".agents/plugins/marketplace.json")] = _json(marketplace)
    return result


def _plugin_files(directory: Path) -> set[Path]:
    if not directory.exists() and not directory.is_symlink():
        return set()
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError(f"Unsafe managed plugin directory: {directory}")
    result: set[Path] = set()
    for file in directory.rglob("*"):
        if file.is_symlink():
            raise ValueError(f"Symlink in managed plugin: {file}")
        if file.is_file():
            result.add(file.relative_to(ROOT))
    return result


def _managed_files() -> set[Path]:
    existing: set[Path] = set()
    for plugin in PLUGIN_NAMES:
        directory = ROOT / "plugins" / f"briareus-{plugin}-workflows"
        existing.update(_plugin_files(directory))
    manifest = ROOT / ".agents/plugins/marketplace.json"
    if manifest.is_file():
        existing.add(manifest.relative_to(ROOT))
    return existing


def reconcile(expected: dict[Path, bytes], *, check: bool) -> list[str]:
    """Update only owned plugin files, rejecting unrelated unexpected paths."""
    stale = sorted(_managed_files() - expected.keys())
    changed = sorted(
        name
        for name, data in expected.items()
        if not (ROOT / name).is_file() or (ROOT / name).read_bytes() != data
    )
    if check and (stale or changed):
        raise ValueError(
            f"Marketplace out of sync: {len(changed)} changed, "
            f"{len(stale)} stale; examples: {(changed + stale)[:5]}"
        )
    if check:
        return []
    for name in stale:
        (ROOT / name).unlink()
    for name in changed:
        destination = ROOT / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(expected[name])
    return [str(name) for name in changed + stale]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--upstream-checkout", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    checkout = args.upstream_checkout.resolve()
    # GitHub repository_dispatch events can be delivered out of order. Do not
    # replace a newer marketplace snapshot with an older, delayed revision.
    source_file = (
        ROOT / "plugins/briareus-github-workflows/skills/ai-agent-git-workflow/SOURCE.json"
    )
    if source_file.is_file():
        old = json.loads(source_file.read_text(encoding="utf-8")).get("revision")
        if isinstance(old, str) and SHA.fullmatch(old) and old != args.revision:
            if (
                subprocess.run(
                    ["git", "-C", str(checkout), "merge-base", "--is-ancestor", args.revision, old],
                    check=False,
                    capture_output=True,
                ).returncode
                == 0
            ):
                print(json.dumps({"skipped_stale": args.revision, "current": old}))
                return
            _git(checkout, "merge-base", "--is-ancestor", old, args.revision)
    bundles = upstream_documents(checkout, args.revision)
    changes = reconcile(expected_files(args.revision, bundles), check=args.check)
    print(
        json.dumps({"upstream": args.revision, "changed_files": len(changes), "check": args.check})
    )


if __name__ == "__main__":
    main()
