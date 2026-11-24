"""Shared MCP tag contract, backed by provider-specific implementations."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations


class TagProvider(Protocol):
    def list_tags(self, repository: str, per_page: int, page: int, /) -> JsonObject: ...
    def create_tag(
        self, repository: str, tag: str, target_ref: str, message: str | None, /
    ) -> JsonObject: ...
    def delete_tag(self, repository: str, tag: str, /) -> JsonObject: ...


def register_tag_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], TagProvider],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    provider: str,
) -> None:
    @mcp.tool(title=f"{provider} list tags", annotations=read_annotations)
    def list_tags(
        account_id: str, repository: str, per_page: int = 100, page: int = 1
    ) -> JsonObject:
        """List repository tags."""
        return client_factory(account_id).list_tags(repository, per_page, page)

    @mcp.tool(title=f"{provider} create tag", annotations=write_annotations)
    def create_tag(
        account_id: str, repository: str, tag: str, target_ref: str, message: str | None = None
    ) -> JsonObject:
        """Create a lightweight or annotated tag at a commit/ref."""
        return client_factory(account_id).create_tag(repository, tag, target_ref, message)

    @mcp.tool(title=f"{provider} delete tag", annotations=destructive_annotations)
    def delete_tag(account_id: str, repository: str, tag: str) -> JsonObject:
        """Delete one repository tag ref."""
        return client_factory(account_id).delete_tag(repository, tag)
