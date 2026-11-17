"""MCP-native project Skills and local source-revision identity for Briareus Hands."""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider
from fastmcp.skills.extension import SkillsExtension
from mcp.types import ToolAnnotations


def _source_fingerprint(roots: list[Path]) -> str:
    digest = hashlib.sha256()
    for root in roots:
        digest.update(root.name.encode("utf-8"))
        digest.update(b"\0")
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix in {".py", ".md"}:
                digest.update(path.relative_to(root).as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
    return "src-" + digest.hexdigest()[:12]


def _shared_publishing_root() -> Path:
    return Path(__file__).resolve().parent / "skills"


def _workflow_roots(shared_publishing: bool, skills_root: Path) -> list[Path]:
    roots = [skills_root]
    if shared_publishing:
        roots.append(_shared_publishing_root())
    return roots


def hand_version(source_root: Path, *, shared_publishing: bool = False) -> str:
    """Expose a verified deployment SHA or a deterministic local-source fingerprint."""
    revision = os.environ.get("SOURCE_COMMIT", "").strip()
    if revision and re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        return "git-" + revision.lower()[:12]
    return _source_fingerprint(_workflow_roots(shared_publishing, source_root))


def register_hand_workflow(
    mcp: FastMCP[None],
    source_root: Path,
    skill_name: str,
    *,
    shared_publishing: bool = False,
) -> None:
    """Expose only Briareus-owned Skills and fallback tools for MCP clients."""
    skills_root = source_root / "skills"
    skill_file = skills_root / skill_name / "SKILL.md"
    if not skill_file.is_file():
        raise FileNotFoundError(f"Required Briareus Hand skill not packaged: {skill_file}")
    shared_skill = _shared_publishing_root() / "source-control-publishing" / "SKILL.md"
    if shared_publishing and not shared_skill.is_file():
        raise FileNotFoundError(f"Required local publishing skill not packaged: {shared_skill}")
    provider = SkillsDirectoryProvider(
        roots=_workflow_roots(shared_publishing, skills_root),
        experimental_skills=True,
    )
    mcp.add_provider(provider)
    mcp.add_extension(SkillsExtension(providers=[provider]))

    def guidance() -> str:
        own = skill_file.read_text(encoding="utf-8")
        if shared_publishing:
            return shared_skill.read_text(encoding="utf-8") + "\n---\n\n" + own
        return own

    @mcp.tool(
        name="read_project_workflow",
        title="Read Briareus Hand workflow",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def read_project_workflow() -> str:
        """Read the locally packaged Briareus-specific workflow for this MCP Hand."""
        return guidance()

    @mcp.prompt(name="project_workflow", title="Briareus Hand workflow")
    def project_workflow() -> str:
        """Load the locally packaged Briareus workflow, independent of external Git."""
        return guidance()
