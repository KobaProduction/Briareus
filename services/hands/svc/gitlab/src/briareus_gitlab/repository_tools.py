from __future__ import annotations

from collections.abc import Callable

from briareus_git.files import FileEncoding
from briareus_git.provider_tools import (
    register_checkout_tools,
    register_file_read,
    register_ref_tools,
)
from briareus_git.tags import register_tag_tools
from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gitlab_client import GitLabClient
from .models import GitLabCommitAction


def register_gitlab_repository_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    register_tag_tools(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations, "GitLab"
    )
    register_file_read(mcp, client_factory, read_annotations, "GitLab")
    register_ref_tools(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations, "GitLab"
    )
    register_checkout_tools(mcp, client_factory, write_annotations, "GitLab", lambda: True)
    _register_local_git(mcp, client_factory, write_annotations)
    _register_repository_reads(mcp, client_factory, read_annotations)
    _register_content_mutations(mcp, client_factory, write_annotations, destructive_annotations)
    _register_branches(mcp, client_factory, read_annotations)


def _register_local_git(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="Push local Git workspace", annotations=write_annotations)
    def push_local_git(
        account_id: str,
        repository: str,
        destination: str,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
        expected_remote_sha: str = "",
    ) -> JsonObject:
        """Push local Git HEAD, optionally using CAS-safe force-with-lease.

        destination is mount-relative, not an absolute terminal cwd; reuse 'path'
        returned by checkout_repository(mode='git'). A stale stored credential
        triggers at most one refresh with the SAME account and project.
        """
        return client_factory(account_id).push_local_git(
            repository,
            destination,
            branch=branch,
            remote=remote,
            set_upstream=set_upstream,
            expected_remote_sha=expected_remote_sha,
        )


def _register_repository_reads(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab repository tree", annotations=read_annotations)
    def list_tree(
        account_id: str,
        project: str,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository tree entries."""
        return client_factory(account_id).list_tree(project, path, ref, recursive, page, per_page)

    @mcp.tool(title="GitLab code search", annotations=read_annotations)
    def search_code(
        account_id: str,
        project: str,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """Search repository blobs inside one project."""
        return client_factory(account_id).search_code(project, search, ref, page, per_page)

    @mcp.tool(title="GitLab list commits", annotations=read_annotations)
    def list_commits(
        account_id: str,
        project: str,
        ref: str = "",
        path: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository commit history, optionally filtered by ref and path."""
        return client_factory(account_id).list_commits(
            project,
            ref,
            path,
            page,
            per_page,
        )


def _register_content_mutations(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab put file", annotations=write_annotations)
    def put_file(
        account_id: str,
        project: str,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
        encoding: FileEncoding = "utf-8",
    ) -> JsonObject:
        """Create or update text or base64 bytes if permitted by GitLab."""
        return client_factory(account_id).put_file(
            project, path, content, commit_message, branch, encoding, last_commit_id=last_commit_id
        )

    @mcp.tool(title="GitLab delete file", annotations=destructive_annotations)
    def delete_file(
        account_id: str,
        project: str,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        """Delete a file if permitted by GitLab."""
        return client_factory(account_id).delete_file(
            project, path, branch, commit_message, last_commit_id
        )

    @mcp.tool(title="GitLab atomic commit", annotations=write_annotations)
    def commit_actions(
        account_id: str,
        project: str,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> JsonObject:
        """Create one atomic multi-file commit using GitLab repository commit actions."""
        return client_factory(account_id).commit_actions(
            project, branch, commit_message, actions, start_branch
        )


def _register_branches(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list branches", annotations=read_annotations)
    def list_branches(
        account_id: str,
        project: str,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List repository branches."""
        return client_factory(account_id).list_branches(project, search, page, per_page)

    @mcp.tool(title="GitLab compare refs", annotations=read_annotations)
    def compare(
        account_id: str,
        project: str,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> JsonObject:
        """Compare two repository refs."""
        return client_factory(account_id).compare(project, from_ref, to_ref, straight)
