from __future__ import annotations

from collections.abc import Callable

from mcp.types import ToolAnnotations

from .account_views import GitHubAccountCapabilities, GitHubAccountList
from .contracts import ToolRegistrar


def register_github_account_tools(
    mcp: ToolRegistrar,
    list_accounts: Callable[[], GitHubAccountList],
    account_capabilities: Callable[[str, str], GitHubAccountCapabilities],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub accounts", annotations=read_annotations)
    def github_accounts() -> GitHubAccountList:
        """List configured GitHub accounts and their potential capability classes."""
        return list_accounts()

    @mcp.tool(title="GitHub account capabilities", annotations=read_annotations)
    def github_account_capabilities(
        account_id: str,
        repository: str = "",
    ) -> GitHubAccountCapabilities:
        """Inspect account-level permissions and optional repository-effective rights."""
        return account_capabilities(account_id, repository)
