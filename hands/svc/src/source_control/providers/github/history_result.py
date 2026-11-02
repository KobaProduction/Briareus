"""Render the typed graph rewrite receipt at the MCP protocol boundary."""

from mcp.types import CallToolResult, TextContent

from .application.history import HistoryRewriteResult
from .application.linear_history import LinearHistoryResult
from .presentation.history_receipts import (
    GraphHistoryReceipt,
    GraphRewriteStep,
    LinearHistoryReceipt,
    LinearRewriteStep,
    RewriteIdentity,
)


def history_result(result: HistoryRewriteResult) -> CallToolResult:
    command, identity = (result.command, result.identity)
    reused = sum(item.reused for item in result.plan)
    payload = GraphHistoryReceipt(
        repository=result.target.repository,
        branch=result.target.branch,
        dry_run=command.dry_run,
        dry_run_creates_unreferenced_commit_objects=command.dry_run,
        identity_source=command.identity_source,
        identity=RewriteIdentity(
            source=identity.source,
            app_id=identity.app_id,
            slug=identity.slug,
            login=identity.login,
            id=identity.bot_id,
            name=identity.name,
            email=identity.email,
        ),
        old_head_sha=result.old_head,
        new_head_sha=result.new_head,
        commit_count=len(result.plan),
        merge_commit_count=sum(len(item.original.parents) > 1 for item in result.plan),
        rewritten_commit_count=len(result.plan) - reused,
        reused_commit_count=reused,
        preserve_messages=command.preserve_messages,
        preserve_trees=command.preserve_trees,
        preserve_author_dates=command.preserve_author_dates,
        final_tree_sha=result.final_tree,
        mapping={item.original.sha: item.new_sha for item in result.plan},
        plan=[
            GraphRewriteStep(
                old_sha=item.original.sha,
                new_sha=item.new_sha,
                tree_sha=item.original.tree,
                message=item.original.message,
                old_parent_shas=list(item.original.parents),
                new_parent_shas=list(item.new_parents),
                reused=item.reused,
            )
            for item in result.plan
        ],
        history_changed=result.new_head != result.old_head,
        old_shas_reachable_from_new_head=any(
            item.original.sha == item.new_sha for item in result.plan
        ),
        ref_updated=result.ref_updated,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=payload.model_dump_json())],
        structured_content=payload.model_dump(mode="json"),
        is_error=False,
    )


def linear_history_result(result: LinearHistoryResult) -> CallToolResult:
    command, identity = (result.command, result.identity)
    payload = LinearHistoryReceipt(
        repository=result.target.repository,
        branch=result.target.branch,
        dry_run=command.dry_run,
        dry_run_creates_unreferenced_commit_objects=command.dry_run,
        identity_source=command.identity_source,
        identity=RewriteIdentity(
            source=identity.source,
            app_id=identity.app_id,
            slug=identity.slug,
            login=identity.login,
            id=identity.bot_id,
            name=identity.name,
            email=identity.email,
        ),
        old_head_sha=result.old_head,
        new_head_sha=result.new_head,
        base_sha=result.base_sha,
        commit_count=len(result.plan),
        preserve_messages=command.preserve_messages,
        preserve_trees=command.preserve_trees,
        preserve_author_dates=command.preserve_author_dates,
        final_tree_sha=result.final_tree,
        mapping={item.original.sha: item.new_sha for item in result.plan},
        plan=[
            LinearRewriteStep(
                old_sha=item.original.sha,
                new_sha=item.new_sha,
                tree_sha=item.original.tree,
                message=item.original.message,
                old_author_date=item.original.author.date,
                old_committer_date=item.original.committer.date,
                new_parent_sha=item.parent,
            )
            for item in result.plan
        ],
        old_shas_reachable_from_new_head=False,
        ref_updated=result.ref_updated,
    )
    return CallToolResult(
        content=[TextContent(type="text", text=payload.model_dump_json())],
        structured_content=payload.model_dump(mode="json"),
        is_error=False,
    )
