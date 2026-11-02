"""Configure and launch the pinned upstream Serena, with bundled LSP engines."""

from __future__ import annotations

import os
from pathlib import Path

from mcp import StdioServerParameters

from .application.prepare_project import PrepareProject
from .confinement import project_root
from .infrastructure.project_preparation import BLOCKED_TOOLS as BLOCKED_TOOLS
from .infrastructure.project_preparation import UpstreamProjectPreparation

UPSTREAM_COMMIT = "4c4268f9c0adf8743a75e6dda2ef1fa635f34cc3"
UPSTREAM_VERSION = "2.0.0"


def prepare_project(relative: str) -> Path:
    project = project_root(relative)
    backend = UpstreamProjectPreparation(Path(os.environ["SERENA_HOME"]))
    return PrepareProject(backend).execute(project).path


def server_parameters(project: Path) -> StdioServerParameters:
    return StdioServerParameters(
        command="/opt/serena/.venv/bin/serena",
        args=[
            "start-mcp-server",
            "--transport",
            "stdio",
            "--context",
            "desktop-app",
            "--language-backend",
            "LSP",
            "--agent-interface",
            "tools",
            "--enable-web-dashboard",
            "false",
            "--enable-gui-log-window",
            "false",
            "--open-web-dashboard",
            "false",
            "--log-level",
            "WARNING",
        ],
        cwd=str(project),
        env={
            "PATH": "/usr/local/bin:/usr/bin:/bin",
            "HOME": "/home/hand",
            "SERENA_HOME": "/home/hand/.serena",
            "UV_OFFLINE": "1",
            "UV_PYTHON_DOWNLOADS": "never",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONUNBUFFERED": "1",
            "SERENA_USAGE_REPORTING": "false",
        },
    )
