from __future__ import annotations

from collections.abc import Callable

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_actions import GitHubActionsClient
from .models import AtomicChange, CopySpec


def register_github_content_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub list directory", annotations=read_annotations)
    def list_directory(
        account_id: str,
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> JsonObject:
        """List one repository directory at an optional ref."""
        return client_factory(account_id).list_directory(repository, path, ref)

    @mcp.tool(
        title="GitHub copy/move existing files",
        annotations=destructive_annotations,
    )
    def copy_files(
        account_id: str,
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: list[CopySpec],
        expected_head_sha: str | None = None,
        operation: str = "copy",
        overwrite: bool = False,
    ) -> JsonObject:
        """Copy or move existing Git blobs between paths/refs without transferring bytes."""
        return client_factory(account_id).copy_files(
            repository, source_ref, branch, message, copies, expected_head_sha, operation, overwrite
        )

    @mcp.tool(title="GitHub atomic commit", annotations=write_annotations)
    def commit_files(
        account_id: str,
        repository: str,
        branch: str,
        message: str,
        changes: list[AtomicChange],
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        """Commit multiple text/binary file changes atomically using Git Data objects."""
        return client_factory(account_id).commit_files(
            repository, branch, message, changes, expected_head_sha
        )

    @mcp.tool(title="GitHub search code", annotations=read_annotations)
    def search_code(
        account_id: str,
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> JsonObject:
        """Search code only inside one allowlisted repository."""
        return client_factory(account_id).search_code(repository, query, per_page, page)
