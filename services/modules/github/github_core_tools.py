from __future__ import annotations

from collections.abc import Callable as Callable

from fastmcp import FastMCP as FastMCP
from mcp.types import ToolAnnotations as ToolAnnotations

from common.runtime_policy_contracts import GitHubRuntimePolicy as GitHubRuntimePolicy
from source_control.providers.github.core_registration import (
    register_github_metadata,
    register_github_ref_comparison,
)

from .content_views import RepositoryContentDelete as RepositoryContentDelete
from .content_views import RepositoryContentWrite as RepositoryContentWrite
from .content_views import RepositoryTextFile as RepositoryTextFile
from .github_identity import GitHubPrettyIdentityClient as GitHubPrettyIdentityClient
from .local_git_views import GitHubCheckout as GitHubCheckout
from .local_git_views import WorkspaceGitAuthorization as WorkspaceGitAuthorization
from .local_git_views import WorkspaceGitPush as WorkspaceGitPush
from .provider_views import RefreshedRateLimits as RefreshedRateLimits
from .provider_views import RepositoryList as RepositoryList
from .provider_views import RepositoryStatus as RepositoryStatus
from .ref_views import BranchList as BranchList
from .ref_views import BranchUpdate as BranchUpdate
from .ref_views import RepositoryComparison as RepositoryComparison


def register_github_core_tools[LifespanT](
    mcp: FastMCP[LifespanT],
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    runtime_policy: Callable[[], GitHubRuntimePolicy],
) -> None:
    register_github_metadata(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations
    )

    @mcp.tool(title="GitHub checkout repository", annotations=write_annotations)
    def github_checkout_repository(
        account_id: str,
        repository: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> GitHubCheckout:
        """Checkout a repository into the shared workspace.

        mode='snapshot' creates a shallow working tree without .git.
        mode='git' keeps full Git metadata and history.
        account_id may be a stable account alias.
        """
        return client_factory(account_id).checkout_repository(
            repository,
            destination,
            mode=mode,
            ref=ref,
            overwrite=overwrite,
        )

    @mcp.tool(title="Authorize local Git workspace", annotations=write_annotations)
    def github_authorize_local_git(
        account_id: str,
        repository: str,
        destination: str,
        remote: str = "origin",
    ) -> WorkspaceGitAuthorization:
        """Authorize an existing local Git checkout for secure Git transport.

        This is additive/experimental. It configures the checkout's ordinary Git credential
        helper using a short-lived selected-account credential and installs a reserved-branch
        pre-push guard. Re-authorize when the credential expires.
        """
        if not runtime_policy().local_git_transport_enabled:
            raise RuntimeError(
                "local Git transport is disabled in application settings; enable it after review"
            )
        return client_factory(account_id).authorize_local_git(
            repository, destination, remote=remote
        )

    @mcp.tool(title="Push local Git workspace", annotations=write_annotations)
    def github_push_local_git(
        account_id: str,
        repository: str,
        destination: str,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> WorkspaceGitPush:
        """Push a validated local Git HEAD through GitHub App/user Git transport.

        Convenience wrapper over the checkout's ordinary Git credential helper. Agents may also
        use normal git fetch/push directly from Terminal after github_authorize_local_git.
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

    register_github_ref_comparison(mcp, client_factory, read_annotations, write_annotations)
