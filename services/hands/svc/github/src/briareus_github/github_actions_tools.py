from __future__ import annotations

from collections.abc import Callable

from briareus_git.ci import CINames, register_ci_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .github_actions import GitHubActionsClient
from .github_admin import repoint_reserved_branch as _repoint_reserved_branch
from .github_history_graph import rewrite_branch_identity_graph as _rewrite_branch_identity_graph


def register_github_actions_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    """Register GitHub capability/history controls plus Actions diagnostics."""
    _register_identity_controls(mcp, client_factory, destructive_annotations)
    register_ci_tools(
        mcp,
        client_factory,
        read_annotations,
        write_annotations,
        destructive_annotations,
        "GitHub",
        CINames("workflow_job_log", "rerun_failed_workflow_jobs", "cancel_workflow_run"),
    )
    _register_diagnostics(mcp, client_factory, read_annotations)
    _register_workflow_actions(mcp, client_factory, write_annotations)


def _register_identity_controls(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(
        title="GitHub rewrite branch identity",
        annotations=destructive_annotations,
    )
    def rewrite_branch_identity(
        account_id: str,
        repository: str,
        branch: str,
        expected_head_sha: str,
        identity_source: str = "current_agent_app",
        preserve_messages: bool = True,
        preserve_trees: bool = True,
        preserve_author_dates: bool = True,
        base_sha: str | None = None,
        max_commits: int = 100,
        dry_run: bool = True,
    ) -> JsonObject:
        """Rewrite linear branch history to the current Agent App Git identity.

        The operation is identity-only: messages and trees must be preserved. It
        requires an expected branch head, supports an exclusive base_sha boundary,
        validates every rewritten tree and the final tree, re-checks the branch
        head immediately before the single forced ref update, and defaults to dry-run.
        """
        return client_factory(account_id).rewrite_branch_identity(
            repository,
            branch,
            expected_head_sha,
            identity_source=identity_source,
            preserve_messages=preserve_messages,
            preserve_trees=preserve_trees,
            preserve_author_dates=preserve_author_dates,
            base_sha=base_sha,
            max_commits=max_commits,
            dry_run=dry_run,
        )

    @mcp.tool(
        title="GitHub rewrite branch identity graph",
        annotations=destructive_annotations,
    )
    def rewrite_branch_identity_graph(
        account_id: str,
        repository: str,
        branch: str,
        expected_head_sha: str,
        identity_source: str = "current_agent_app",
        preserve_messages: bool = True,
        preserve_trees: bool = True,
        preserve_author_dates: bool = True,
        max_commits: int = 500,
        dry_run: bool = True,
    ) -> JsonObject:
        """Rewrite a reachable merge DAG to the current Agent App Git identity.

        Parent ordering/topology, commit trees, messages, and optional original Git
        dates are preserved. The operation requires an expected branch head, validates
        the reconstructed DAG and final tree, performs one CAS-style head re-check,
        and only then force-replaces the branch ref. Dry-run creates unreachable Git
        commit objects so the returned old->new mapping is exact.
        """
        return _rewrite_branch_identity_graph(
            client_factory(account_id),
            repository,
            branch,
            expected_head_sha,
            identity_source=identity_source,
            preserve_messages=preserve_messages,
            preserve_trees=preserve_trees,
            preserve_author_dates=preserve_author_dates,
            max_commits=max_commits,
            dry_run=dry_run,
        )

    @mcp.tool(
        title="GitHub repoint reserved branch",
        annotations=destructive_annotations,
    )
    def repoint_reserved_branch(
        account_id: str,
        repository: str,
        branch: str,
        expected_head_sha: str,
        target_sha: str,
        dry_run: bool = True,
    ) -> JsonObject:
        """Repoint a Bridge-reserved branch without changing its repository tree.

        This is a narrow maintenance primitive, not a general force-ref operation.
        The target commit must have the same tree as the current reserved branch,
        must already use the current Agent App identity, and the branch must not be
        the repository default branch or GitHub-protected. The operation requires an
        expected head SHA, re-checks it immediately before the forced ref update, and
        defaults to dry-run.
        """
        return _repoint_reserved_branch(
            client_factory(account_id),
            repository,
            branch,
            expected_head_sha,
            target_sha,
            dry_run=dry_run,
        )


def _register_diagnostics(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub workflow files", annotations=read_annotations)
    def workflow_files(
        account_id: str,
        repository: str,
        run_id: int,
        per_page: int = 100,
        page: int = 1,
    ) -> JsonObject:
        """List files produced by one GitHub Actions workflow run."""
        return client_factory(account_id).list_workflow_files(
            repository,
            run_id,
            per_page,
            page,
        )

    @mcp.tool(title="GitHub download workflow file", annotations=read_annotations)
    def download_workflow_file(
        account_id: str,
        repository: str,
        workflow_file_id: int,
        max_bytes: int = 8 * 1024 * 1024,
    ) -> JsonObject:
        """Download a small workflow file ZIP as base64 with SHA-256."""
        return client_factory(account_id).download_workflow_file(
            repository,
            workflow_file_id,
            max_bytes,
        )


def _register_workflow_actions(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitHubActionsClient],
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitHub enable workflow", annotations=write_annotations)
    def enable_workflow(
        account_id: str,
        repository: str,
        workflow_id: str,
    ) -> JsonObject:
        """Enable one GitHub Actions workflow."""
        return client_factory(account_id).enable_workflow(repository, workflow_id)

    @mcp.tool(title="GitHub dispatch workflow", annotations=write_annotations)
    def dispatch_workflow(
        account_id: str,
        repository: str,
        workflow_id: str,
        ref: str,
        inputs: JsonObject | None = None,
    ) -> JsonObject:
        """Dispatch a workflow_dispatch workflow with an explicit ref and inputs."""
        return client_factory(account_id).dispatch_workflow(
            repository,
            workflow_id,
            ref,
            inputs,
        )

    @mcp.tool(title="GitHub rerun workflow job", annotations=write_annotations)
    def rerun_workflow_job(
        account_id: str,
        repository: str,
        job_id: int,
    ) -> JsonObject:
        """Re-run one GitHub Actions job."""
        return client_factory(account_id).rerun_workflow_job(repository, job_id)

    @mcp.tool(title="GitHub rerun workflow run", annotations=write_annotations)
    def rerun_workflow_run(
        account_id: str,
        repository: str,
        run_id: int,
    ) -> JsonObject:
        """Re-run every job in one workflow run."""
        return client_factory(account_id).rerun_workflow_run(repository, run_id)
