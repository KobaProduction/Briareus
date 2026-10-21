"""Configure and launch the pinned upstream Serena, with bundled LSP engines."""
from __future__ import annotations
import json
import os
from pathlib import Path
from .confinement import project_root

UPSTREAM_COMMIT = "4c4268f9c0adf8743a75e6dda2ef1fa635f34cc3"
UPSTREAM_VERSION = "2.0.0"
BLOCKED_TOOLS = frozenset({"open_dashboard"})


def prepare_project(relative):
    # These APIs are the real pinned Serena project/config implementation.
    from serena.config.serena_config import SerenaConfig, ProjectConfig
    from solidlsp.ls_config import LanguageServerId
    project = project_root(relative)
    home = Path(os.environ["SERENA_HOME"])
    if home != Path("/home/hand/.serena") or home.is_symlink():
        raise ValueError("Private placement Serena home required")
    home.mkdir(mode=0o700, parents=True, exist_ok=True)
    managed = home / "project"
    managed.mkdir(mode=0o700, exist_ok=True)
    configuration = {
        "language_backend": "LSP", "agent_interface": "tools", "projects": [],
        "web_dashboard": False, "web_dashboard_open_on_launch": False, "gui_log_window": False,
        "log_level": 30, "trace_lsp_communication": False, "tool_timeout": None,
        "project_serena_folder_location": str(managed), "trusted_project_path_patterns": [],
        "excluded_tools": sorted(BLOCKED_TOOLS),
        "included_optional_tools": ["restart_language_server", "get_diagnostics_for_file"],
        "ls_specific_settings": {
            "python": {"ls_path": "/usr/local/bin/pyright-langserver"},
            "typescript": {"ls_path": "/usr/local/bin/typescript-language-server"},
            "cpp": {"ls_path": "/usr/bin/clangd-14"},
        },
    }
    target = home / "serena_config.yml"
    target.write_text(json.dumps(configuration), encoding="utf-8")
    target.chmod(0o600)
    config = SerenaConfig.from_config_file()
    selected = set()
    scanned = 0
    for directory, folders, filenames in os.walk(project, followlinks=False):
        folders[:] = [name for name in folders if name not in {".git", ".venv", "node_modules", ".serena", "build", "dist"}
                      and not (Path(directory) / name).is_symlink()]
        for name in filenames:
            scanned += 1
            if scanned > 100000:
                raise ValueError("Explicit project subtree required for a larger source workspace")
            suffix = Path(name).suffix.lower()
            if suffix in {".py", ".pyi"}:
                selected.add(LanguageServerId.PYTHON)
            elif suffix in {".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"}:
                selected.add(LanguageServerId.TYPESCRIPT)
            elif suffix in {".c", ".h", ".cpp", ".hpp", ".cc", ".cxx"}:
                selected.add(LanguageServerId.CPP)
    # An empty workspace has no language/project to activate. Do not invent a
    # Python project merely to make MCP metadata or module health available.
    if selected:
        languages = sorted(selected, key=lambda language: language.value)
        ProjectConfig.autogenerate(project, config, project_name="Briareus project", languages=languages,
                                   interactive=False, asynchronous=False)
    return project


def server_parameters(project):
    from mcp import StdioServerParameters
    return StdioServerParameters(command="/opt/serena/.venv/bin/serena", args=[
        "start-mcp-server", "--transport", "stdio", "--context", "desktop-app",
        "--language-backend", "LSP", "--agent-interface", "tools",
        "--enable-web-dashboard", "false", "--enable-gui-log-window", "false",
        "--open-web-dashboard", "false", "--log-level", "WARNING"],
        cwd=str(project), env={"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/home/hand",
            "SERENA_HOME": "/home/hand/.serena", "UV_OFFLINE": "1", "UV_PYTHON_DOWNLOADS": "never",
            "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1", "SERENA_USAGE_REPORTING": "false"})
