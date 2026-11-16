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


def hand_version(source_root: Path) -> str:
    """Expose the deployed commit when present, otherwise a source fingerprint."""
    revision = os.environ.get("SOURCE_COMMIT", "").strip()
    if revision and re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        return "git-" + revision.lower()[:12]

    # Standalone test/dev deployments don't necessarily carry a Git checkout.
    digest = hashlib.sha256()
    for path in sorted(source_root.rglob("*")):
        if not path.is_file() or path.suffix not in {".py", ".md"}:
            continue
        digest.update(path.relative_to(source_root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return "src-" + digest.hexdigest()[:12]


def register_hand_workflow(mcp: FastMCP[None], source_root: Path, skill_name: str) -> None:
    """Provide SEP-2640 skills and a tool/prompt fallback for older clients."""
    skills_root = source_root / "skills"
    skill_file = skills_root / skill_name / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError(f"Required Hand skill not packaged: {skill_file}")
    provider = SkillsDirectoryProvider(roots=skills_root, experimental_skills=True)
    mcp.add_provider(provider)
    mcp.add_extension(SkillsExtension(providers=[provider]))

    @mcp.tool(
        name="read_project_workflow",
        title="Read canonical project workflow",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def read_project_workflow() -> str:
        """Read project guidance before clone, edit, or publish operations.

        Includes canonical checkout paths, required preflight and safe handoffs.
        """
        return skill_file.read_text(encoding="utf-8")

    @mcp.prompt(name="project_workflow", title="Canonical project workflow")
    def project_workflow() -> str:
        """Load the documented repository/project workflow for this Hand."""
        return skill_file.read_text(encoding="utf-8")
