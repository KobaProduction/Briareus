"""Concrete MCP projections of the domain history rewrite receipts."""

from pydantic import BaseModel


class RewriteIdentity(BaseModel):
    source: str
    app_id: str
    slug: str
    login: str
    id: int
    name: str
    email: str


class RewriteStep(BaseModel):
    old_sha: str
    new_sha: str
    tree_sha: str
    message: str


class GraphRewriteStep(RewriteStep):
    old_parent_shas: list[str]
    new_parent_shas: list[str]
    reused: bool


class LinearRewriteStep(RewriteStep):
    old_author_date: str
    old_committer_date: str
    new_parent_sha: str | None


class HistoryReceipt(BaseModel):
    repository: str
    branch: str
    dry_run: bool
    dry_run_creates_unreferenced_commit_objects: bool
    identity_source: str
    identity: RewriteIdentity
    old_head_sha: str
    new_head_sha: str
    commit_count: int
    preserve_messages: bool
    preserve_trees: bool
    preserve_author_dates: bool
    final_tree_sha: str
    mapping: dict[str, str]
    old_shas_reachable_from_new_head: bool
    ref_updated: bool


class GraphHistoryReceipt(HistoryReceipt):
    merge_commit_count: int
    rewritten_commit_count: int
    reused_commit_count: int
    plan: list[GraphRewriteStep]
    history_changed: bool


class LinearHistoryReceipt(HistoryReceipt):
    base_sha: str | None
    plan: list[LinearRewriteStep]
