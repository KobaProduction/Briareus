from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from briareus_json_values import JsonObject
from fastmcp import FastMCP
from mcp.types import ToolAnnotations

from .gitlab_client import GitLabClient
from .reviews import DiffPosition


def register_gitlab_review_tools(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    _register_approvals(mcp, client_factory, read_annotations, write_annotations)
    _register_threads(mcp, client_factory, read_annotations, write_annotations)
    _register_notes(
        mcp, client_factory, read_annotations, write_annotations, destructive_annotations
    )


def _register_approvals(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab merge request approvals", annotations=read_annotations)
    def get_merge_request_approvals(
        account_id: str, project: str, iid: int, include_rules: bool = False
    ) -> JsonObject:
        """Read approvals and optionally effective approval rules (tier-dependent)."""
        return client_factory(account_id).get_merge_request_approvals(project, iid, include_rules)

    @mcp.tool(title="GitLab set approval", annotations=write_annotations)
    def set_merge_request_approval(
        account_id: str, project: str, iid: int, approved: bool, expected_head_sha: str = ""
    ) -> JsonObject:
        """Approve the exact expected HEAD or withdraw the selected account's approval."""
        return client_factory(account_id).set_merge_request_approval(
            project, iid, approved, expected_head_sha
        )

    @mcp.tool(title="GitLab list reviewers", annotations=read_annotations)
    def list_reviewers(account_id: str, project: str, iid: int) -> JsonObject:
        """Read assigned reviewers and their review state."""
        return client_factory(account_id).list_reviewers(project, iid)

    @mcp.tool(title="GitLab set reviewers", annotations=write_annotations)
    def set_reviewers(
        account_id: str, project: str, iid: int, reviewer_ids: list[int]
    ) -> JsonObject:
        """Replace reviewer assignments with explicit user IDs; [] removes all."""
        return client_factory(account_id).set_reviewers(project, iid, reviewer_ids)

    @mcp.tool(title="GitLab rebase merge request", annotations=write_annotations)
    def rebase_merge_request(
        account_id: str, project: str, iid: int, expected_head_sha: str
    ) -> JsonObject:
        """Queue a same-project rebase after a HEAD precheck (not atomic CAS).

        Poll get_merge_request for completion.
        """
        return client_factory(account_id).rebase_merge_request(project, iid, expected_head_sha)

    @mcp.tool(title="GitLab request review changes", annotations=write_annotations)
    def request_review_changes(
        account_id: str, project: str, iid: int, expected_head_sha: str
    ) -> JsonObject:
        """Request changes after a HEAD precheck; provider GraphQL support is required."""
        return client_factory(account_id).request_review_changes(project, iid, expected_head_sha)

    @mcp.tool(title="GitLab set merge request draft", annotations=write_annotations)
    def set_merge_request_draft(account_id: str, project: str, iid: int, draft: bool) -> JsonObject:
        """Mark a merge request as draft or ready for review."""
        return client_factory(account_id).set_merge_request_draft(project, iid, draft)


def _register_threads(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list review threads", annotations=read_annotations)
    def list_review_threads(
        account_id: str, project: str, iid: int, page: int = 1, per_page: int = 100
    ) -> JsonObject:
        """List paginated MR discussions including inline comments and resolution state."""
        return client_factory(account_id).list_review_threads(project, iid, page, per_page)

    @mcp.tool(title="GitLab create review thread", annotations=write_annotations)
    def create_review_thread(
        account_id: str, project: str, iid: int, body: str, position: DiffPosition | None = None
    ) -> JsonObject:
        """Create a general or inline review thread.

        Inline coordinates must match current diff_refs.
        """
        return client_factory(account_id).create_review_thread(project, iid, body, position)

    @mcp.tool(title="GitLab reply to review thread", annotations=write_annotations)
    def reply_to_review_thread(
        account_id: str, project: str, iid: int, thread_id: str, body: str
    ) -> JsonObject:
        """Reply to a discussion by its GitLab thread ID."""
        return client_factory(account_id).reply_to_review_thread(project, iid, thread_id, body)

    @mcp.tool(title="GitLab update review comment", annotations=write_annotations)
    def update_review_comment(
        account_id: str, project: str, iid: int, thread_id: str, comment_id: int, body: str
    ) -> JsonObject:
        """Edit a discussion comment using the selected account's provider rights."""
        return client_factory(account_id).update_review_comment(
            project, iid, thread_id, comment_id, body
        )

    @mcp.tool(title="GitLab set review thread resolved", annotations=write_annotations)
    def set_review_thread_resolved(
        account_id: str, project: str, iid: int, thread_id: str, resolved: bool
    ) -> JsonObject:
        """Resolve or reopen a merge request discussion."""
        return client_factory(account_id).set_review_thread_resolved(
            project, iid, thread_id, resolved
        )


def _register_notes(
    mcp: FastMCP[None],
    client_factory: Callable[[str], GitLabClient],
    read_annotations: ToolAnnotations,
    write_annotations: ToolAnnotations,
    destructive_annotations: ToolAnnotations,
) -> None:
    @mcp.tool(title="GitLab list notes", annotations=read_annotations)
    def list_notes(
        account_id: str,
        project: str,
        target: Literal["issue", "merge_request"],
        iid: int,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        """List paginated issue or merge request notes."""
        return client_factory(account_id).list_notes(project, target, iid, page, per_page)

    @mcp.tool(title="GitLab update note", annotations=write_annotations)
    def update_note(
        account_id: str,
        project: str,
        target: Literal["issue", "merge_request"],
        iid: int,
        note_id: int,
        body: str,
    ) -> JsonObject:
        """Edit an issue or merge request note."""
        return client_factory(account_id).update_note(project, target, iid, note_id, body)

    @mcp.tool(title="GitLab delete note", annotations=destructive_annotations)
    def delete_note(
        account_id: str,
        project: str,
        target: Literal["issue", "merge_request"],
        iid: int,
        note_id: int,
        confirm: bool = False,
    ) -> JsonObject:
        """Delete an issue or merge request note only with explicit confirmation."""
        return client_factory(account_id).delete_note(project, target, iid, note_id, confirm)
