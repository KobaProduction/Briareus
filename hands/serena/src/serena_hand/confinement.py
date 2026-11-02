"""Filesystem adapter confining paths before invoking real Serena MCP tools."""

from pathlib import Path, PurePosixPath

from mcp.types import CallToolRequestParams
from pydantic import BaseModel, ConfigDict, field_validator


class _ProjectSelectors(BaseModel):
    model_config = ConfigDict(extra="ignore", strict=True, frozen=True)
    project: str | None = None
    project_name: str | None = None
    relative_path: str | None = None
    file_path: str | None = None
    path: str | None = None
    cwd: str | None = None
    target_path: str | None = None

    @field_validator("relative_path", "file_path", "path", "cwd", "target_path", mode="before")
    @classmethod
    def optional_path(cls, value: object) -> str | None:
        if not value:
            return None
        if not isinstance(value, str):
            raise ValueError("Confined project path required")
        return value


def project_root(relative: str, workspace: Path = Path("/project-data")) -> Path:
    if not isinstance(relative, str):
        raise ValueError("Relative project path required")
    if (
        not relative
        or "\\" in relative
        or ":" in relative
        or "\0" in relative
        or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts
    ):
        raise ValueError("Relative project path required")
    root = workspace.resolve(strict=True)
    selected = (root / relative).resolve(strict=True)
    if not selected.is_relative_to(root) or not selected.is_dir():
        raise ValueError("Project must remain inside its own workspace")
    return selected


def _require_project_alias(value: str | None, project: Path) -> None:
    if value is None:
        return
    if value not in {
        ".",
        project.name,
        "Briareus project",
        str(project),
    }:
        raise ValueError("Only the placement project can be activated or queried")


def _require_confined_path(value: str | None, project: Path) -> None:
    if not value:
        return
    if "\0" in value or "\\" in value:
        raise ValueError("Confined project path required")
    candidate = Path(value)
    selected = (candidate if candidate.is_absolute() else project / candidate).resolve()
    if not selected.is_relative_to(project):
        raise ValueError("Tool path leaves the placement project")


def confine_arguments(call: CallToolRequestParams, project: Path) -> CallToolRequestParams:
    tool = call.name
    if tool in {"open_dashboard", "jet_brains_debug"} or tool.startswith("jet_brains_"):
        raise ValueError("Host UI and external IDE surfaces are not a Node LSP tool")
    selectors = _ProjectSelectors.model_validate(call.arguments or {})
    for alias in (selectors.project, selectors.project_name):
        _require_project_alias(alias, project)
    for path in (
        selectors.relative_path,
        selectors.file_path,
        selectors.path,
        selectors.cwd,
        selectors.target_path,
    ):
        _require_confined_path(path, project)
    return call
