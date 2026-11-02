"""Workspace import/export operations consumed by MCP presentation."""

from typing import Protocol

from project_runtime_client.analysis.domain.artifacts import (
    WorkspaceArtifactExport,
    WorkspaceImportReceipt,
)


class WorkspaceTransfers(Protocol):
    async def import_workspace_file(
        self,
        project_id: str,
        workspace_path: str,
        project_folder: str = "/",
        language: str = "",
        compiler_spec: str = "",
        auto_analyze: bool = True,
    ) -> WorkspaceImportReceipt: ...

    async def import_workspace_program(
        self,
        project_id: str,
        workspace_path: str,
        target_folder: str = "/",
        target_name: str = "",
        overwrite: bool = False,
    ) -> WorkspaceImportReceipt: ...

    async def restore_workspace_project(
        self, project_id: str, workspace_path: str, project_name: str, parent_dir: str = ""
    ) -> WorkspaceImportReceipt: ...

    async def export_program_to_workspace(
        self, project_id: str, program_name: str, workspace_path: str, *, overwrite: bool = False
    ) -> WorkspaceArtifactExport: ...

    async def archive_project_to_workspace(
        self, project_id: str, workspace_path: str, *, overwrite: bool = False
    ) -> WorkspaceArtifactExport: ...
