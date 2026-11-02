from __future__ import annotations

from typing import TYPE_CHECKING

from modules.gitlab.tool_context import GitLabRuntimeContext

if TYPE_CHECKING:
    from mcp.types import ToolAnnotations

    from source_control.providers.github.contracts import ToolRegistrar


def register_gitlab_tools(
    mcp: ToolRegistrar,
    context: GitLabRuntimeContext,
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    from modules.gitlab.issue_tools import register_gitlab_issue_tools
    from modules.gitlab.merge_request_tools import register_gitlab_merge_request_tools
    from modules.gitlab.pipeline_tools import register_gitlab_pipeline_tools
    from modules.gitlab.profile_tools import register_gitlab_profile_tools
    from modules.gitlab.repository_tools import register_gitlab_repository_tools

    register_gitlab_profile_tools(
        mcp,
        context.accounts,
        context.account_capabilities,
        context.client,
        read_annotations,
    )
    register_gitlab_repository_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_gitlab_merge_request_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
    )
    register_gitlab_issue_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
    )
    register_gitlab_pipeline_tools(
        mcp,
        context.client,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
