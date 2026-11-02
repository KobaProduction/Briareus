"""Workspace custody remains in its owner-provided implementation."""

from pathlib import Path
from typing import Protocol

from project_runtime_client.analysis.domain.workspace import WorkspaceFileMetadata


class AnalysisWorkspacePort(Protocol):
    def path_for(self, relative: str) -> Path: ...

    def target_path(self, relative: str) -> Path: ...

    def sha256(self, relative: str) -> str: ...

    def file_info(self, relative: str) -> WorkspaceFileMetadata | None: ...
