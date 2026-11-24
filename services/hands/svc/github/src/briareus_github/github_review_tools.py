from __future__ import annotations

from collections.abc import Callable

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_review import GitHubReviewClient


def register_github_review_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubReviewClient],
    read_annotations: ToolAnnotations,
) -> None:
    """Register detailed review reads."""

    @mcp.tool(title="GitHub conversation comments", annotations=read_annotations)
    def list_conversation_comments(
        account_id: str,
        repository: str,
        number: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List one page of top-level issue/PR comments; use next_page to continue."""
        return client_factory(account_id).list_conversation_comments(
            repository, number, page, per_page
        )

    @mcp.tool(title="GitHub inline review comments", annotations=read_annotations)
    def list_review_comments(
        account_id: str,
        repository: str,
        number: int,
    ) -> JsonObject:
        """List inline review comments for a pull request."""
        return client_factory(account_id).list_review_comments(repository, number)
