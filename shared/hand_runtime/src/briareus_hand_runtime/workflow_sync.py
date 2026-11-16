"""Fetch allowlisted AI Agent Workflow skills at MCP image build time."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import tarfile
import urllib.request
from pathlib import Path

REPOSITORY = "ArthurKoba/ai-agent-workflow"
ARCHIVE_LIMIT = 16 * 1024 * 1024
FILE_LIMIT = 128 * 1024
SHA_PATTERN = re.compile(r"^[0-9a-f]{40}$")
GIT_PATHS = (
    "AGENTS.md",
    "skills/git-workflow.md",
    "skills/git-workflow/commits.md",
    "skills/git-workflow/publication.md",
    "skills/orchestration/README.md",
    "skills/orchestration/participants.md",
    "skills/orchestration/cycle.md",
    "skills/orchestration/communication.md",
    "skills/orchestration/pipeline.md",
    "skills/orchestration/workspace.md",
    "docs/REPORTING_PROTOCOL.md",
)
DEPLOY_PATHS = ("AGENTS.md", "skills/terminal-operations.md", "docs/MCP_STRATEGY.md")


def is_allowed(bundle: str, name: str) -> bool:
    if bundle == "git":
        return name in GIT_PATHS
    return name in DEPLOY_PATHS or (
        name.startswith("skills/services-deployment/") and name.endswith(".md")
    )


def mandatory_paths(bundle: str) -> tuple[str, ...]:
    if bundle == "git":
        return GIT_PATHS
    return (*DEPLOY_PATHS, "skills/services-deployment/README.md",
            "skills/services-deployment/coolify-compose.md")


def _archive_member_name(bundle: str, member: tarfile.TarInfo) -> str | None:
    prefix, sep, name = member.name.partition("/")
    if not sep or not prefix.startswith("ai-agent-workflow-"):
        return None
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or "\\" in name:
        raise ValueError("Unsafe archive member")
    if not is_allowed(bundle, name):
        return None
    return name


def _read_document(stream: tarfile.TarFile, member: tarfile.TarInfo) -> bytes:
    if not member.isfile() or member.size > FILE_LIMIT or member.size < 0:
        raise ValueError(f"Invalid workflow document: {member.name}")
    src = stream.extractfile(member)
    if src is None:
        raise ValueError(f"Unreadable workflow document: {member.name}")
    data = src.read(FILE_LIMIT + 1)
    data.decode("utf-8")
    if len(data) != member.size:
        raise ValueError(f"Truncated workflow document: {member.name}")
    return data


def select_documents(bundle: str, archive: bytes) -> dict[str, bytes]:
    """Inspect archive members directly; never unpack untrusted paths."""
    if len(archive) > ARCHIVE_LIMIT:
        raise ValueError("Archive exceeds configured limit")
    found: dict[str, bytes] = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as stream:
        for member in stream:
            name = _archive_member_name(bundle, member)
            if name is None:
                continue
            if name in found:
                raise ValueError(f"Duplicate workflow document: {name}")
            found[name] = _read_document(stream, member)
            if len(found) > 80:
                raise ValueError("Too many workflow files")
    missing = set(mandatory_paths(bundle)) - found.keys()
    if missing:
        raise ValueError(f"Missing mandatory workflow files: {sorted(missing)}")
    return found


def router(bundle: str, revision: str) -> str:
    if bundle == "git":
        name = "ai-agent-git-workflow"
        module = "skills/git-workflow.md"
        directions = (
            "Read references/AGENTS.md and references/skills/git-workflow.md. "
            "Before commits read references/skills/git-workflow/commits.md; before "
            "publication read references/skills/git-workflow/publication.md; for "
            "multi-agent work read references/skills/orchestration/README.md and "
            "its routed modules."
        )
    else:
        name = "ai-agent-services-deployment"
        module = "skills/services-deployment/README.md"
        directions = (
            "Read references/AGENTS.md, then "
            "references/skills/services-deployment/README.md. When Coolify owns "
            "Compose, read references/skills/services-deployment/coolify-compose.md. "
            "Read only task-relevant modules for networking, secrets, migration, "
            "variables and runtime acceptance."
        )
    return (
        "---\n"
        f"name: {name}\n"
        f'description: "Build-synchronized agent workflow library for {bundle} tasks."\n'
        "---\n\n"
        "# Upstream AI Agent Workflow snapshot\n\n"
        f"Source: https://github.com/{REPOSITORY}/tree/{revision}\n\n"
        f"Built from Git commit: {revision}. This snapshot is frozen for the image;\n"
        "it does not refresh continuously at runtime.\n\n"
        f"{directions}\n\n"
        f"Primary module: references/{module}\n"
    )


def install_snapshot(bundle: str, revision: str, archive: bytes, root: Path) -> Path:
    if bundle not in {"git", "coolify"} or not SHA_PATTERN.fullmatch(revision):
        raise ValueError("Invalid bundle or revision")
    files = select_documents(bundle, archive)
    parent = "skills" if bundle == "git" else "deployment_skills"
    name = "ai-agent-git-workflow" if bundle == "git" else "ai-agent-services-deployment"
    target = root / parent / name
    target.mkdir(parents=True, exist_ok=False)
    (target / "SKILL.md").write_text(router(bundle, revision), encoding="utf-8")
    for name, data in sorted(files.items()):
        path = target / "references" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    provenance = {
        "repository": REPOSITORY, "revision": revision, "bundle": bundle,
        "files": {name: hashlib.sha256(data).hexdigest() for name, data in sorted(files.items())},
    }
    (target / "SOURCE.json").write_text(json.dumps(provenance, indent=2) + "\n")
    return target


def read_url(url: str, limit: int) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "Briareus-MCP-Workflow-Build", "Accept": "application/json",
    })
    with urllib.request.urlopen(request, timeout=25) as response:
        data: bytes = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError("Workflow download exceeds limit")
    return data


def fetch_source(ref_file: Path | None = None) -> tuple[str, bytes]:
    if ref_file is not None:
        response = ref_file.read_bytes()
        if len(response) > 32_768:
            raise ValueError("Upstream ref file exceeds limit")
    else:
        response = read_url(
            f"https://api.github.com/repos/{REPOSITORY}/git/ref/heads/main", 32_768
        )
    doc = json.loads(response)
    revision = doc.get("object", {}).get("sha", "")
    if not isinstance(revision, str) or not SHA_PATTERN.fullmatch(revision):
        raise ValueError("No valid upstream commit SHA")
    archive = read_url(
        f"https://codeload.github.com/{REPOSITORY}/tar.gz/{revision}", ARCHIVE_LIMIT
    )
    return revision, archive


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--bundle", choices=("git", "coolify"), required=True)
    parser.add_argument("--source-root", type=Path,
                        default=Path(__file__).resolve().parent)
    parser.add_argument("--ref-file", type=Path)
    args = parser.parse_args()
    revision, archive = fetch_source(args.ref_file)
    path = install_snapshot(args.bundle, revision, archive, args.source_root)
    print(f"Synced {REPOSITORY}@{revision}: {path}")


if __name__ == "__main__":
    main()
