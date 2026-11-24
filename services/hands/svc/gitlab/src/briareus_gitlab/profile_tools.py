from __future__ import annotations

from collections.abc import Callable

from briareus_git.provider_tools import register_account_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gitlab_client import GitLabClient


def register_gitlab_profile_tools(
    mcp: FastMCP[None],
    accounts_factory: Callable[[], JsonObject],
    account_capabilities_factory: Callable[[str, str], JsonObject],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    register_account_tools(
        mcp, accounts_factory, account_capabilities_factory, read_annotations, "GitLab"
    )

    @mcp.tool(title="GitLab account status", annotations=read_annotations)
    def account_status(account_id: str) -> JsonObject:
        """Verify one explicit GitLab account and report the authenticated user."""
        return client_factory(account_id).profile_status()

    @mcp.tool(title="GitLab list projects", annotations=read_annotations)
    def list_projects(
        account_id: str,
        search: str = "",
        membership: bool = True,
        owned: bool = False,
        min_access_level: int = 0,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List projects visible to the selected GitLab account."""
        return client_factory(account_id).list_projects(
            search, membership, owned, min_access_level, page, per_page
        )

    @mcp.tool(title="GitLab project status", annotations=read_annotations)
    def project_status(account_id: str, project: str) -> JsonObject:
        """Read project metadata using a numeric project id or path_with_namespace."""
        return client_factory(account_id).project_status(project)

    @mcp.tool(title="GitLab create project", annotations=write_annotations)
    def create_project(
        account_id: str,
        name: str,
        path: str = "",
        namespace: str = "",
        visibility: str = "private",
        description: str = "",
        initialize_with_readme: bool = False,
    ) -> JsonObject:
        """Create a GitLab project (private by default) for the user or namespace.

        An explicit namespace must resolve to an exact GitLab group/user path.
        The provider enforces project creation rights and token scopes.
        Check remote state before retrying a failed or interrupted creation.
        """
        return client_factory(account_id).create_project(
            name,
            path=path,
            namespace=namespace,
            visibility=visibility,
            description=description,
            initialize_with_readme=initialize_with_readme,
        )
