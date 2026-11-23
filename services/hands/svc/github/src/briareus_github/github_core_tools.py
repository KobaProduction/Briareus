from __future__ import annotations

from collections.abc import Callable

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

    @mcp.tool(title="GitHub get file", annotations=read_annotations)
    def get_file(
        account_id: str,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> JsonObject:
        """Read one UTF-8 repository file at an optional ref."""
        return client_factory(account_id).get_file(repository, path, ref)

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
    @mcp.tool(title="GitHub create branch", annotations=write_annotations)
    def create_branch(
        account_id: str,
        repository: str,
        branch: str,
        from_branch: str = "main",
    ) -> JsonObject:
        """Create a non-protected working branch from an existing branch or ref."""
        return client_factory(account_id).create_branch(repository, branch, from_branch)

    @mcp.tool(title="GitHub put file", annotations=write_annotations)
    def put_file(
        account_id: str,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> JsonObject:
        """Create or update one UTF-8 file on a non-protected working branch."""
        return client_factory(account_id).put_file(repository, path, content, message, branch)

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
    @mcp.tool(title="GitHub checkout repository", annotations=write_annotations)
    def checkout_repository(
        account_id: str,
        repository: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        """Checkout a repository into the shared workspace.

        mode='snapshot' creates a shallow working tree without .git.
        mode='git' keeps full Git metadata and history.
        account_id may be a stable account alias. destination MUST be relative to
        SERVER_MOUNT_PATH, e.g. 'projects/heating-station' (not
        '/workspace/projects/heating-station'). Inspect existing Server workspaces
        and matching Git remotes; never add dates or an extra /repo directory.
        Copy the returned 'path' as the
        destination in subsequent GitHub local-Git tools.
        For Terminal fetch/pull/push, use mode='git', then call
        authorize_local_git with the same account_id, repository and
        destination. Checkout authentication alone does not persist Terminal Git auth.
        """
        return client_factory(account_id).checkout_repository(
            repository,
            destination,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
        )

    @mcp.tool(title="Authorize Server terminal Git fetch/pull/push", annotations=write_annotations)
    def authorize_local_git(
        account_id: str,
        repository: str,
        destination: str,
        remote: str = "origin",
    ) -> JsonObject:
        """Connect a GitHub MCP account to Git fetch/pull/push in a Server terminal checkout.

        Recovery tool for Terminal errors such as 'could not read Username',
        'Authentication failed' or expired Git credentials. Before asking the user
        for credentials, inspect accounts and use the account authorized for
        the repository work. repository is owner/name; destination is the checkout
        root relative to the Server mount, e.g. projects/ai-science.
        NEVER pass the absolute terminal cwd '/workspace/projects/ai-science':
        remove the SERVER_MOUNT_PATH prefix or copy 'path' from checkout_repository.
        A laptop path or workspace_id alone is not this checkout. remote defaults to origin.

        Configures ordinary Git's credential helper and a reserved-branch pre-push
        guard. Retry the failed Terminal command after success. Current credentials
        can expire: re-authorize then. Tokens must not be copied into chat or other
        files. Respect identity/publication restrictions and disabled transport policy.
        This configures authentication; it does not fetch, push or reset branches.
        """
        if not runtime_policy().local_git_transport_enabled:
            raise RuntimeError(
                "local Git transport is disabled in application settings; enable it after review"
            )
        return client_factory(account_id).authorize_local_git(
            repository, destination, remote=remote
        )

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
