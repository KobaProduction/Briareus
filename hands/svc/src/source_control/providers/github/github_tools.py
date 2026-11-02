from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

from modules.github.github_actions import GitHubActionsClient

if TYPE_CHECKING:
    from mcp.types import ToolAnnotations

    from source_control.providers.github.contracts import ToolRegistrar


def register_github_workflow_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    """Register the extended GitHub development workflow tools."""
    from modules.github.content_tools import register_github_content_tools
    from modules.github.issue_tools import register_github_issue_tools
    from modules.github.pull_tools import register_github_pull_tools
    from modules.github.ref_tools import register_github_ref_tools
    from modules.github.run_tools import register_github_run_tools

    register_github_content_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_github_ref_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
        destructive_annotations,
    )
    register_github_pull_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
    )
    register_github_issue_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
    )
    register_github_run_tools(
        mcp,
        client_factory,
        read_annotations,
    )
