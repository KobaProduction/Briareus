"""MCP-native workflow guidance and source-revision identity for selected Hands."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from fastmcp.skills.extension import SkillsExtension
from mcp.types import ToolAnnotations


def hand_version(source_root: Path, *, shared_publishing: bool = False) -> str:
    """Expose the deployed commit when present, otherwise a source fingerprint."""
    revision = os.environ.get("SOURCE_COMMIT", "").strip()
    if revision and re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        return "git-" + revision.lower()[:12]

    # Standalone test/dev deployments don't necessarily carry a Git checkout.
    digest = hashlib.sha256()
    roots = (source_root, _shared_publishing_root()) if shared_publishing else (source_root,)
    for root in roots:
        digest.update(root.name.encode("utf-8"))
        digest.update(b"\0")
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in {".py", ".md"}:
                continue
            digest.update(path.relative_to(root).as_posix().encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
    return "src-" + digest.hexdigest()[:12]


def _shared_publishing_root() -> Path:
    return Path(__file__).resolve().parent / "skills"


def register_hand_workflow(
    mcp: FastMCP[None], source_root: Path, skill_name: str, *, shared_publishing: bool = False
) -> None:
    """Provide provider and optionally shared Skills plus older-client fallbacks."""
    skills_root = source_root / "skills"
    skill_file = skills_root / skill_name / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError(f"Required Hand skill not packaged: {skill_file}")
    shared_skill = _shared_publishing_root() / "source-control-publishing" / "SKILL.md"
    if shared_publishing and not shared_skill.is_file():
        raise FileNotFoundError(f"Required shared publishing skill not packaged: {shared_skill}")
    roots = [skills_root, _shared_publishing_root()] if shared_publishing else [skills_root]
    provider = SkillsDirectoryProvider(roots=roots, experimental_skills=True)
    mcp.add_provider(provider)
    mcp.add_extension(SkillsExtension(providers=[provider]))

    def guidance() -> str:
        own = skill_file.read_text(encoding="utf-8")
        if not shared_publishing:
            return own
        return shared_skill.read_text(encoding="utf-8") + "\n---\n\n" + own

    @mcp.tool(
        name="read_project_workflow",
        title="Read canonical project workflow",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def read_project_workflow() -> str:
        """Read shared Git publication rules plus this provider's project procedure."""
        return guidance()

    @mcp.prompt(name="project_workflow", title="Canonical project workflow")
    def project_workflow() -> str:
        """Load shared publication rules and this Hand's project procedure."""
        return guidance()
