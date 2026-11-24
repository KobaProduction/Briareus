from __future__ import annotations

from collections.abc import Callable

from briareus_git.provider_tools import register_issue_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gitlab_client import GitLabClient


def register_gitlab_issue_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    register_issue_tools(mcp, client_factory, read_annotations, write_annotations, "GitLab")

    @mcp.tool(title="GitLab list issues", annotations=read_annotations)
    def list_issues(
        account_id: str,
        project: str,
        state: str = "opened",
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List project issues."""
        return client_factory(account_id).list_issues(project, state, search, page, per_page)
