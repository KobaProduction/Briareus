from __future__ import annotations

from collections.abc import Callable

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations


def register_github_account_tools(
    mcp: FastMCP[None],
    list_accounts: Callable[[], JsonObject],
    account_capabilities_factory: Callable[[str, str], JsonObject],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub accounts", annotations=read_annotations)
    def accounts() -> JsonObject:
        """List configured GitHub accounts and their potential capability classes."""
        return list_accounts()

    @mcp.tool(title="GitHub account capabilities", annotations=read_annotations)
    def account_capabilities(
        account_id: str,
        repository: str = "",
    ) -> JsonObject:
        """Inspect account-level permissions and optional repository-effective rights."""
        return account_capabilities_factory(account_id, repository)
