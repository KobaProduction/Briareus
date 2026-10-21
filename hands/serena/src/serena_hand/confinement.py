"""Placement paths are confined before invoking the real Serena MCP tools."""
from pathlib import Path, PurePosixPath


def project_root(relative, workspace=Path("/project-data")):
    if (not isinstance(relative, str) or not relative or "\\" in relative
        or ":" in relative or "\0" in relative or PurePosixPath(relative).is_absolute()
        or ".." in PurePosixPath(relative).parts):
        raise ValueError("Relative project path required")
    root = workspace.resolve(strict=True)
    selected = (root / relative).resolve(strict=True)
    if not selected.is_relative_to(root) or not selected.is_dir():
        raise ValueError("Project must remain inside its own workspace")
    return selected


def confine_arguments(tool, arguments, project):
    if not isinstance(arguments, dict):
        raise ValueError("Original tool arguments required")
    if tool in {"open_dashboard", "jet_brains_debug"} or tool.startswith("jet_brains_"):
        raise ValueError("Host UI and external IDE surfaces are not a Node LSP tool")
    for key, value in arguments.items():
        if key in {"project", "project_name"} and value is not None:
            if not isinstance(value, str) or value not in {".", project.name, "Briareus project", str(project)}:
                raise ValueError("Only the placement project can be activated or queried")
        if key in {"relative_path", "file_path", "path", "cwd", "target_path"} and value:
            if not isinstance(value, str) or "\0" in value or "\\" in value:
                raise ValueError("Confined project path required")
            candidate = Path(value)
            selected = (candidate if candidate.is_absolute() else project / candidate).resolve()
            if not selected.is_relative_to(project):
                raise ValueError("Tool path leaves the placement project")
    return arguments
