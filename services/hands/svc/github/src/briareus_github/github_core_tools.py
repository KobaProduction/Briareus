from __future__ import annotations

from collections.abc import Callable

from briareus_git.files import FileEncoding, RepositoryFileProvider
from briareus_git.provider_tools import (
    register_checkout_tools,
    register_file_read,
    register_ref_tools,
)
from briareus_github_policy import GitHubRuntimePolicy
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_identity import GitHubPrettyIdentityClient


def register_github_core_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    runtime_policy: Callable[[], GitHubRuntimePolicy],
) -> None:
    register_file_read(mcp, client_factory, read_annotations, "GitHub")
    register_ref_tools(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations, "GitHub"
    )
    register_checkout_tools(
        mcp,
        client_factory,
        write_annotations,
        "GitHub",
        lambda: runtime_policy().local_git_transport_enabled,
    )
    _register_repository_reads(mcp, client_factory, read_annotations)
    _register_repository_creation(mcp, client_factory, write_annotations)
    _register_content_mutations(mcp, client_factory, write_annotations, destructive_annotations)
    _register_local_git(mcp, client_factory, write_annotations, runtime_policy)
    _register_ref_updates(mcp, client_factory, read_annotations, write_annotations)


def _register_repository_reads(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub list repositories", annotations=read_annotations)
    def list_repositories(account_id: str) -> JsonObject:
        """List repositories currently accessible to the selected GitHub account."""
        return client_factory(account_id).list_repositories()

    @mcp.tool(title="GitHub status", annotations=read_annotations)
    def status(account_id: str, repository: str) -> JsonObject:
        """Verify access and basic repository metadata for the selected account."""
        return client_factory(account_id).status(repository)

    @mcp.tool(title="GitHub rate limits", annotations=read_annotations)
    def rate_limits(account_id: str, repository: str = "") -> JsonObject:
        """Refresh and report GitHub API rate-limit buckets for the selected identity."""
        return client_factory(account_id).refresh_rate_limits(repository)

    @mcp.tool(title="GitHub list branches", annotations=read_annotations)
    def list_branches(account_id: str, repository: str) -> JsonObject:
        """List repository branches visible to the selected account."""
        return client_factory(account_id).list_branches(repository)


def _register_repository_creation(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub create repository", annotations=write_annotations)
    def create_repository(
        account_id: str,
        owner: str,
        name: str,
        private: bool = True,
        description: str = "",
        auto_init: bool = False,
    ) -> JsonObject:
        """Create a repository under an explicit GitHub owner; private by default.

        Requires owner installation permissions (repository_creation:write or
        administration:write) or a user token with adequate rights.
        A new repository may not be accessible to a selected-repositories-only
        App installation until the installation's repository selection is updated.
        Do not retry creation on ambiguous network failures; check whether it exists.
        """
        return client_factory(account_id).create_repository(
            owner, name, private=private, description=description, auto_init=auto_init
        )


def _register_content_mutations(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub put file", annotations=write_annotations)
    def put_file(
        account_id: str,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        encoding: FileEncoding = "utf-8",
    ) -> JsonObject:
        """Create or update one file on a non-protected working branch.

        Supply UTF-8 text or valid base64 bytes in content, according to encoding.
        """
        client: RepositoryFileProvider = client_factory(account_id)
        return client.put_file(repository, path, content, message, branch, encoding)

    @mcp.tool(title="GitHub delete file", annotations=destructive_annotations)
    def delete_file(
        account_id: str,
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> JsonObject:
        """Delete one file from a non-protected working branch."""
        return client_factory(account_id).delete_file(repository, path, message, branch)


def _register_local_git(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    write_annotations: ToolAnnotations,
    runtime_policy: Callable[[], GitHubRuntimePolicy],
) -> None:
    @mcp.tool(title="Push local Git workspace", annotations=write_annotations)
    def push_local_git(
        account_id: str,
        repository: str,
        destination: str,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> JsonObject:
        """Push a validated local Git HEAD through GitHub App/user Git transport.

        Convenience wrapper over the checkout's ordinary Git credential helper. Agents may also
        use normal git fetch/push directly from Terminal after authorize_local_git.
        destination MUST be relative to SERVER_MOUNT_PATH (copy the checkout 'path');
        absolute paths and Terminal cwd are not valid destination arguments.
        If the stored Git credential expired, this tool refreshes the SAME account
        once and retries; authorization/branch policy failures are never bypassed.
        """
        if not runtime_policy().local_git_transport_enabled:
            raise RuntimeError(
                "local Git transport is disabled in application settings; enable it after review"
            )
        return client_factory(account_id).push_local_git(
            repository,
            destination,
            branch=branch,
            remote=remote,
            set_upstream=set_upstream,
        )


def _register_ref_updates(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub compare refs", annotations=read_annotations)
    def compare(
        account_id: str,
        repository: str,
        base: str,
        head: str,
    ) -> JsonObject:
        """Compare two refs and return commit/file differences."""
        return client_factory(account_id).compare(repository, base, head)

    @mcp.tool(title="GitHub fast-forward branch", annotations=write_annotations)
    def fast_forward(
        account_id: str,
        repository: str,
        branch: str,
        to_ref: str,
    ) -> JsonObject:
        """Fast-forward a non-protected working branch to an existing descendant ref."""
        return client_factory(account_id).fast_forward(repository, branch, to_ref)
