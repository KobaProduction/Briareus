from __future__ import annotations

from collections.abc import Callable

from fastmcp import FastMCP as FastMCP
from mcp.types import CallToolResult, ToolAnnotations

from source_control.providers.github.contracts import ToolRegistrar
from source_control.providers.gitlab.merge_receipts import (
    MergeRequestDiffPage,
    MergeRequestNoteResult,
    MergeRequestPage,
    MergeRequestResult,
)

from .gitlab_client import GitLabClient
from .presentation.merge_results import merge_request_result


def register_gitlab_merge_request_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        title="GitLab list merge requests",
        annotations=read_annotations,
        output_schema=MergeRequestPage.model_json_schema(),
    )
    def list_merge_requests(
        account_id: str,
        project: str,
        state: str = "opened",
        source_branch: str = "",
        target_branch: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> CallToolResult:
        """List merge requests for one project."""
        return merge_request_result(
            client_factory(account_id).list_merge_requests(
                project,
                state,
                source_branch,
                target_branch,
                page,
                per_page,
            )
        )

    @mcp.tool(
        title="GitLab get merge request",
        annotations=read_annotations,
        output_schema=MergeRequestResult.model_json_schema(),
    )
    def get_merge_request(
        account_id: str,
        project: str,
        iid: int,
    ) -> CallToolResult:
        """Read one merge request."""
        return merge_request_result(client_factory(account_id).get_merge_request(project, iid))

    @mcp.tool(
        title="GitLab create merge request",
        annotations=write_annotations,
        output_schema=MergeRequestResult.model_json_schema(),
    )
    def create_merge_request(
        account_id: str,
        project: str,
        source_branch: str,
        target_branch: str,
        title: str,
        description: str = "",
        remove_source_branch: bool = False,
        squash: bool = False,
        draft: bool = False,
    ) -> CallToolResult:
        """Create a merge request inside one GitLab project."""
        return merge_request_result(
            client_factory(account_id).create_merge_request(
                project,
                source_branch,
                target_branch,
                title,
                description,
                remove_source_branch,
                squash,
                draft,
            )
        )

    @mcp.tool(
        title="GitLab update merge request",
        annotations=write_annotations,
        output_schema=MergeRequestResult.model_json_schema(),
    )
    def update_merge_request(
        account_id: str,
        project: str,
        iid: int,
        title: str | None = None,
        description: str | None = None,
        state_event: str | None = None,
        target_branch: str | None = None,
        remove_source_branch: bool | None = None,
        squash: bool | None = None,
    ) -> CallToolResult:
        """Update merge request metadata or state."""
        return merge_request_result(
            client_factory(account_id).update_merge_request(
                project,
                iid,
                title,
                description,
                state_event,
                target_branch,
                remove_source_branch,
                squash,
            )
        )

    @mcp.tool(
        title="GitLab merge request diffs",
        annotations=read_annotations,
        output_schema=MergeRequestDiffPage.model_json_schema(),
    )
    def list_merge_request_diffs(
        account_id: str,
        project: str,
        iid: int,
        page: int = 1,
        per_page: int = 100,
    ) -> CallToolResult:
        """List changed-file diffs for one merge request."""
        return merge_request_result(
            client_factory(account_id).list_merge_request_diffs(
                project,
                iid,
                page,
                per_page,
            )
        )

    @mcp.tool(
        title="GitLab merge request note",
        annotations=write_annotations,
        output_schema=MergeRequestNoteResult.model_json_schema(),
    )
    def add_merge_request_note(
        account_id: str,
        project: str,
        iid: int,
        body: str,
    ) -> CallToolResult:
        """Add a discussion note/comment to one merge request."""
        return merge_request_result(
            client_factory(account_id).add_merge_request_note(project, iid, body)
        )

    @mcp.tool(
        title="GitLab merge merge request",
        annotations=write_annotations,
        output_schema=MergeRequestResult.model_json_schema(),
    )
    def merge_merge_request(
        account_id: str,
        project: str,
        iid: int,
        sha: str = "",
        squash: bool | None = None,
        should_remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        merge_commit_message: str = "",
        squash_commit_message: str = "",
    ) -> CallToolResult:
        """Merge a merge request, optionally pinning the expected source SHA."""
        return merge_request_result(
            client_factory(account_id).merge_merge_request(
                project,
                iid,
                sha,
                squash,
                should_remove_source_branch,
                merge_when_pipeline_succeeds,
                merge_commit_message,
                squash_commit_message,
            )
        )
