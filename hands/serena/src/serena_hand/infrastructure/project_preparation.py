"""Translate detected languages into the pinned Serena configuration API."""

import json
import os
import subprocess
from collections.abc import Iterable
from pathlib import Path

from serena_hand.domain.languages import IGNORED_FOLDERS, SourceLanguage

BLOCKED_TOOLS = frozenset({"open_dashboard"})


class UpstreamProjectPreparation:
    def __init__(self, home: Path) -> None:
        if home != Path("/home/hand/.serena") or home.is_symlink():
            raise ValueError("Private placement Serena home required")
        self._home = home
        self._configured = False

    def configure(self) -> None:
        self._home.mkdir(mode=0o700, parents=True, exist_ok=True)
        managed = self._home / "project"
        managed.mkdir(mode=0o700, exist_ok=True)
        target = self._home / "serena_config.yml"
        target.write_text(
            json.dumps(
                {
                    "language_backend": "LSP",
                    "agent_interface": "tools",
                    "projects": [],
                    "web_dashboard": False,
                    "web_dashboard_open_on_launch": False,
                    "gui_log_window": False,
                    "log_level": 30,
                    "trace_lsp_communication": False,
                    "tool_timeout": None,
                    "project_serena_folder_location": str(managed),
                    "trusted_project_path_patterns": [],
                    "excluded_tools": sorted(BLOCKED_TOOLS),
                    "included_optional_tools": [
                        "restart_language_server",
                        "get_diagnostics_for_file",
                    ],
                    "ls_specific_settings": {
                        "python": {"ls_path": "/usr/local/bin/pyright-langserver"},
                        "typescript": {"ls_path": "/usr/local/bin/typescript-language-server"},
                        "cpp": {"ls_path": "/usr/bin/clangd-14"},
                    },
                }
            ),
            encoding="utf-8",
        )
        target.chmod(0o600)
        self._configured = True

    def filenames(self, project: Path) -> Iterable[str]:
        for directory, folders, filenames in os.walk(project, followlinks=False):
            folders[:] = [
                name
                for name in folders
                if name not in IGNORED_FOLDERS and not (Path(directory) / name).is_symlink()
            ]
            yield from filenames

    def activate(self, project: Path, languages: tuple[SourceLanguage, ...]) -> None:
        if not self._configured:
            raise RuntimeError("Private configuration must be prepared before project activation")
        subprocess.run(  # noqa: S603 -- fixed pinned interpreter and validated private project/languages
            [
                "/opt/serena/.venv/bin/python",
                "-m",
                "serena_hand.infrastructure.upstream_project",
                str(project),
                *(language.name for language in languages),
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
