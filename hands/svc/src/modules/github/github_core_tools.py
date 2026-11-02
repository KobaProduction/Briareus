from __future__ import annotations

from collections.abc import Callable as Callable
from copy import deepcopy as deepcopy

from mcp.types import CallToolResult as CallToolResult
from mcp.types import ToolAnnotations as ToolAnnotations

from common.tool_registration import ToolRegistrar as ToolRegistrar
from hand_runtime.provider_schemas import JSON_OBJECT_OUTPUT_SCHEMA as JSON_OBJECT_OUTPUT_SCHEMA
from service_runtime.runtime_policy_contracts import GitHubRuntimePolicy as GitHubRuntimePolicy
from source_control.providers.github.core_registration import (
    register_github_metadata,
    register_github_ref_comparison,
)
from svc_hand.local_git_result import local_git_result as local_git_result

from .content_views import RepositoryContentDelete as RepositoryContentDelete
from .content_views import RepositoryContentWrite as RepositoryContentWrite
from .content_views import RepositoryTextFile as RepositoryTextFile
from .github_identity import GitHubPrettyIdentityClient as GitHubPrettyIdentityClient
from .provider_views import RefreshedRateLimits as RefreshedRateLimits
from .provider_views import RepositoryList as RepositoryList
from .provider_views import RepositoryStatus as RepositoryStatus
from .ref_views import BranchList as BranchList
from .ref_views import BranchUpdate as BranchUpdate
from .ref_views import RepositoryComparison as RepositoryComparison


def register_github_core_tools(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
    runtime_policy: Callable[[], GitHubRuntimePolicy],
) -> None:
    register_github_metadata(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations
    )
    _register_local_git(mcp, client_factory, write_annotations, runtime_policy)
    register_github_ref_comparison(mcp, client_factory, read_annotations, write_annotations)


def _register_local_git(
    mcp: ToolRegistrar,
    client_factory: Callable[[str], GitHubPrettyIdentityClient],
    write_annotations: ToolAnnotations,
    runtime_policy: Callable[[], GitHubRuntimePolicy],
) -> None:
    @mcp.tool(
        title="GitHub checkout repository",
        annotations=write_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_checkout_repository(
        account_id: str,
        repository: str,
        destination: str,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> CallToolResult:
        """Checkout a repository into the shared workspace.

        mode='snapshot' exports files without .git. mode='git' creates an agent
        worktree backed by one canonical repository per project. Existing data
        is preserved even when overwrite=true; choose another destination.
        account_id may be a stable account alias.
        """
        return local_git_result(
            client_factory(account_id).checkout_repository(
                repository,
                destination,
                mode=mode,
                ref=ref,
                overwrite=overwrite,
            )
        )

    @mcp.tool(
        title="GitHub create agent worktree",
        annotations=write_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_create_worktree(
        account_id: str, repository: str, destination: str, branch: str, ref: str = ""
    ) -> CallToolResult:
        """Reuse one project-local repository and create an isolated agent branch/worktree.

        destination is inside the current project only. Existing paths are never overwritten.
        Use local Git from this worktree, then authorized MCP push and PR merge.
        """
        return local_git_result(
            client_factory(account_id).create_worktree(repository, destination, branch, ref)
        )

    @mcp.tool(
        title="Authorize local Git workspace",
        annotations=write_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_authorize_local_git(
        account_id: str,
        repository: str,
        destination: str,
        remote: str = "origin",
    ) -> CallToolResult:
        """Authorize an existing local Git checkout for secure Git transport.

        This is additive/experimental. It configures the checkout's ordinary Git credential
        helper using a short-lived selected-account credential and installs a reserved-branch
        pre-push guard. Re-authorize when the credential expires.
        """
        if not runtime_policy().local_git_transport_enabled:
            raise RuntimeError(
                "local Git transport is disabled in application settings; enable it after review"
            )
        return local_git_result(
            client_factory(account_id).authorize_local_git(repository, destination, remote=remote)
        )

    @mcp.tool(
        title="Push local Git workspace",
        annotations=write_annotations,
        output_schema=deepcopy(JSON_OBJECT_OUTPUT_SCHEMA),
    )
    def github_push_local_git(
        account_id: str,
        repository: str,
        destination: str,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
    ) -> CallToolResult:
        """Push a validated local Git HEAD through GitHub App/user Git transport.

        Convenience wrapper over the checkout's ordinary Git credential helper. Agents may also
        use normal git fetch/push directly from Terminal after github_authorize_local_git.
        """
        if not runtime_policy().local_git_transport_enabled:
            raise RuntimeError(
                "local Git transport is disabled in application settings; enable it after review"
            )
        return local_git_result(
            client_factory(account_id).push_local_git(
                repository,
                destination,
                branch=branch,
                remote=remote,
                set_upstream=set_upstream,
            )
        )
