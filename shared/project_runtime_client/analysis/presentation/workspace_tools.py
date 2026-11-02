"""MCP adapters for workspace import/export."""

from fastmcp import FastMCP
from mcp.types import CallToolResult

from project_runtime_client.analysis.application.workspace_transfers import WorkspaceTransfers

from .transfer_results import WorkspaceImportResult, export_result


def register_workspace_transfer_tools[StateT](
    mcp: FastMCP[StateT],
    transfers: WorkspaceTransfers,
) -> None:
    @mcp.tool(title="Import workspace file")
    async def import_workspace_file(
        project_id: str,
        workspace_path: str,
        project_folder: str = "/",
        language: str = "",
        compiler_spec: str = "",
        auto_analyze: bool = True,
    ) -> WorkspaceImportResult:
        """Import a shared-workspace file through the isolated analysis staging boundary."""
        return WorkspaceImportResult.model_validate(
            await transfers.import_workspace_file(
                project_id,
                workspace_path,
                project_folder,
                language,
                compiler_spec,
                auto_analyze,
            )
        )

    @mcp.tool(title="Import workspace program package")
    async def import_workspace_program(
        project_id: str,
        workspace_path: str,
        target_folder: str = "/",
        target_name: str = "",
        overwrite: bool = False,
    ) -> WorkspaceImportResult:
        """Import a workspace program package through isolated staging."""
        return WorkspaceImportResult.model_validate(
            await transfers.import_workspace_program(
                project_id,
                workspace_path,
                target_folder,
                target_name,
                overwrite,
            )
        )

    @mcp.tool(title="Restore workspace project archive")
    async def restore_workspace_project(
        project_id: str,
        workspace_path: str,
        project_name: str,
        parent_dir: str = "",
    ) -> WorkspaceImportResult:
        """Restore a workspace project archive through isolated staging."""
        return WorkspaceImportResult.model_validate(
            await transfers.restore_workspace_project(
                project_id,
                workspace_path,
                project_name,
                parent_dir,
            )
        )

    @mcp.tool(title="Export program to workspace")
    async def export_program_to_workspace(
        project_id: str,
        program_name: str,
        workspace_path: str,
        overwrite: bool = False,
    ) -> CallToolResult:
        """Export one analysis program into a normal shared-workspace file."""
        return export_result(
            await transfers.export_program_to_workspace(
                project_id,
                program_name,
                workspace_path,
                overwrite=overwrite,
            )
        )

    @mcp.tool(title="Archive project to workspace")
    async def archive_project_to_workspace(
        project_id: str,
        workspace_path: str,
        overwrite: bool = False,
    ) -> CallToolResult:
        """Archive an analysis project into a normal shared-workspace file."""
        return export_result(
            await transfers.archive_project_to_workspace(
                project_id,
                workspace_path,
                overwrite=overwrite,
            )
        )
