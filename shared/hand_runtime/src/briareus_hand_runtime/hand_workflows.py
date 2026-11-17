"""MCP-native workflow guidance and source-revision identity for selected Hands."""

from __future__ import annotations

import hashlib
import json
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


def _upstream_suffix(bundle: str) -> str:
    if not bundle:
        return ""
    manifest = _build_snapshot_root(bundle) / "SOURCE.json"
    if not manifest.is_file():
        return ""
    revision = json.loads(manifest.read_text(encoding="utf-8")).get("revision")
    if isinstance(revision, str) and re.fullmatch(r"[0-9a-f]{40}", revision):
        return "-workflow-" + revision[:12]
    return ""


def hand_version(
    source_root: Path, *, shared_publishing: bool = False, shared_deployment: bool = False
) -> str:
    """Expose deployed commit and upstream skill SHA, else source fingerprint."""
    revision = os.environ.get("SOURCE_COMMIT", "").strip()
    if revision and re.fullmatch(r"[0-9a-fA-F]{7,40}", revision):
        bundle = "git" if shared_publishing else "coolify" if shared_deployment else ""
        return "git-" + revision.lower()[:12] + _upstream_suffix(bundle)
    return _source_fingerprint(
        _workflow_roots(shared_publishing, shared_deployment, source_root)
    )


def _shared_publishing_root() -> Path:
    return Path(__file__).resolve().parent / "skills"


def _shared_deployment_root() -> Path:
    return Path(__file__).resolve().parent / "deployment_skills"


def _build_snapshot_root(bundle: str) -> Path:
    if bundle == "git":
        return _shared_publishing_root() / "ai-agent-git-workflow"
    return _shared_deployment_root() / "ai-agent-services-deployment"


def _workflow_roots(
    shared_publishing: bool, shared_deployment: bool, skills_root: Path
) -> list[Path]:
    roots = [skills_root]
    if shared_publishing:
        roots.append(_shared_publishing_root())
    if shared_deployment:
        roots.append(_shared_deployment_root())
    return roots


def _read_reference(bundle: str, path: str) -> str:
    root = (_build_snapshot_root(bundle) / "references").resolve()
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts or relative.suffix != ".md":
        raise ValueError("Invalid workflow reference path")
    target = (root / relative).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        raise FileNotFoundError("Unknown workflow reference")
    if target.stat().st_size > 128 * 1024:
        raise ValueError("Reference size exceeds limit")
    return target.read_text(encoding="utf-8")


def _check_workflow_sources(
    skill_file: Path, shared_publishing: bool, shared_deployment: bool
) -> None:
    if not skill_file.is_file():
        raise FileNotFoundError(f"Required Hand skill not packaged: {skill_file}")
    shared_skill = _shared_publishing_root() / "source-control-publishing" / "SKILL.md"
    if shared_publishing and not shared_skill.is_file():
        raise FileNotFoundError(f"Required publishing skill not packaged: {shared_skill}")
    if os.getenv("BRIAREUS_REQUIRE_SYNCED_SKILLS") == "true":
        bundle = "git" if shared_publishing else "coolify" if shared_deployment else ""
        if bundle and not (_build_snapshot_root(bundle) / "SKILL.md").is_file():
            raise FileNotFoundError("Missing build-synchronized workflow bundle: " + bundle)


def _publish_reference_tool(
    mcp: FastMCP[None], shared_publishing: bool, shared_deployment: bool
) -> None:
    @mcp.tool(
        name="read_workflow_reference",
        title="Read bundled workflow reference",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def read_workflow_reference(bundle: str, path: str) -> str:
        """Read one downloaded workflow document with verified relative paths."""
        if bundle not in {"git", "coolify"}:
            raise ValueError("bundle must be git or coolify")
        if bundle == "git" and not shared_publishing:
            raise ValueError("Git workflow references unavailable for this Hand")
        if bundle == "coolify" and not shared_deployment:
            raise ValueError("Coolify workflow references unavailable for this Hand")
        return _read_reference(bundle, path)


def register_hand_workflow(
    mcp: FastMCP[None],
    source_root: Path,
    skill_name: str,
    *,
    shared_publishing: bool = False,
    shared_deployment: bool = False,
) -> None:
    """Provide provider and optionally shared Skills plus older-client fallbacks."""
    skills_root = source_root / "skills"
    skill_file = skills_root / skill_name / "SKILL.md"
    _check_workflow_sources(skill_file, shared_publishing, shared_deployment)
    provider = SkillsDirectoryProvider(
        roots=_workflow_roots(shared_publishing, shared_deployment, skills_root),
        experimental_skills=True,
    )
    mcp.add_provider(provider)
    mcp.add_extension(SkillsExtension(providers=[provider]))

    def guidance() -> str:
        own = skill_file.read_text(encoding="utf-8")
        if not shared_publishing:
            return own
        shared_skill = _shared_publishing_root() / "source-control-publishing" / "SKILL.md"
        return shared_skill.read_text(encoding="utf-8") + "\n---\n\n" + own

    @mcp.tool(
        name="read_project_workflow",
        title="Read canonical project workflow",
        annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False),
    )
    def read_project_workflow() -> str:
        """Read shared policy and this Hand's project workflow."""
        return guidance()

    if shared_publishing or shared_deployment:
        _publish_reference_tool(mcp, shared_publishing, shared_deployment)

    @mcp.prompt(name="project_workflow", title="Canonical project workflow")
    def project_workflow() -> str:
        """Load shared policy and this Hand's project workflow."""
        return guidance()
