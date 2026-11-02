"""Rebuild a complete reachable DAG, then recheck the branch before one ref update."""

from dataclasses import dataclass, replace
from typing import Protocol

from source_control.providers.github.application._bindings import _SourceBinding
from source_control.providers.github.domain.history import (
    CommitGraph,
    GitCommit,
    GitIdentity,
    HistoryRewriteError,
    require_identity_only,
)


@dataclass(frozen=True, slots=True)
class RewriteTarget:
    repository: str
    branch: str


@dataclass(frozen=True, slots=True)
class AgentIdentity:
    source: str
    app_id: str
    slug: str
    login: str
    bot_id: int
    name: str
    email: str

    @property
    def git(self) -> GitIdentity:
        return GitIdentity(self.name, self.email)


@dataclass(frozen=True, slots=True)
class RewriteCommand:
    repository: str
    branch: str
    expected_head_sha: str
    identity_source: str = "current_agent_app"
    preserve_messages: bool = True
    preserve_trees: bool = True
    preserve_author_dates: bool = True
    max_commits: int = 500
    dry_run: bool = True


@dataclass(frozen=True, slots=True)
class CommitRewrite:
    original: GitCommit
    new_sha: str
    new_parents: tuple[str, ...]
    reused: bool


@dataclass(frozen=True, slots=True)
class HistoryRewriteResult:
    target: RewriteTarget
    command: RewriteCommand
    identity: AgentIdentity
    old_head: str
    new_head: str
    final_tree: str
    plan: tuple[CommitRewrite, ...]
    ref_updated: bool = False


class GitHistory(Protocol):
    def allowed_target(self, repository: str, branch: str) -> RewriteTarget: ...
    def head(self, target: RewriteTarget, *, confirming: bool = False) -> str: ...
    def commit(self, target: RewriteTarget, sha: str) -> GitCommit: ...
    def identity(self) -> AgentIdentity: ...
    def create(
        self,
        target: RewriteTarget,
        original: GitCommit,
        parents: tuple[str, ...],
        identity: GitIdentity,
        *,
        preserve_dates: bool,
    ) -> GitCommit: ...
    def replace_head(self, target: RewriteTarget, sha: str) -> None: ...


class CommitGraphLoader(_SourceBinding[GitHistory]):
    """Application collaborator: domain traversal checks surround each provider read."""

    def load(self, target: RewriteTarget, head: str, maximum: int) -> tuple[GitCommit, ...]:
        graph = CommitGraph(maximum)
        self.visit(graph, target, head)
        if not graph.order:
            raise HistoryRewriteError("rewrite graph contains no commits")
        return tuple(graph.order)

    def visit(self, graph: CommitGraph, target: RewriteTarget, sha: str) -> None:
        if not graph.enter(sha):
            return
        commit = self.source.commit(target, sha)
        for parent in commit.parents:
            self.visit(graph, target, parent)
        graph.finish(commit)


class RewriteHistory(_SourceBinding[GitHistory]):
    def rewrite_commits(
        self,
        target: RewriteTarget,
        commits: tuple[GitCommit, ...],
        identity: GitIdentity,
        *,
        preserve_dates: bool,
    ) -> tuple[CommitRewrite, ...]:
        mapping: dict[str, str] = {}
        plan: list[CommitRewrite] = []
        for original in commits:
            parents = tuple(mapping[parent] for parent in original.parents)
            reused = original.matches_identity(identity) and parents == original.parents
            created = (
                original
                if reused
                else self.source.create(
                    target, original, parents, identity, preserve_dates=preserve_dates
                )
            )
            if not reused:
                created.require_rewritten(original, parents, identity)
            mapping[original.sha] = created.sha
            plan.append(CommitRewrite(original, created.sha, parents, reused))
        if len(mapping) != len(commits):
            raise HistoryRewriteError(
                "rewritten commit count does not match source graph commit count"
            )
        return tuple(plan)

    def execute(self, command: RewriteCommand) -> HistoryRewriteResult:
        target = self.source.allowed_target(command.repository, command.branch)
        require_identity_only(
            command.expected_head_sha,
            command.identity_source,
            preserve_messages=command.preserve_messages,
            preserve_trees=command.preserve_trees,
        )
        expected = command.expected_head_sha.strip()
        old_head = self.source.head(target)
        if old_head != expected:
            raise HistoryRewriteError(f"branch head changed: expected {expected}, found {old_head}")
        commits = CommitGraphLoader(self.source).load(
            target, old_head, max(1, min(command.max_commits, 2000))
        )
        identity = self.source.identity()
        identity.git.require_complete()
        plan = self.rewrite_commits(
            target, commits, identity.git, preserve_dates=command.preserve_author_dates
        )
        final = self.source.commit(target, plan[-1].new_sha)
        if final.tree != commits[-1].tree:
            raise HistoryRewriteError(
                f"final tree mismatch: expected {commits[-1].tree}, found {final.tree}"
            )
        result = HistoryRewriteResult(
            target, command, identity, old_head, plan[-1].new_sha, final.tree, plan
        )
        return self.update_ref(result, expected)

    def update_ref(self, result: HistoryRewriteResult, expected: str) -> HistoryRewriteResult:
        if result.command.dry_run or result.new_head == result.old_head:
            return result
        current = self.source.head(result.target, confirming=True)
        if current != expected:
            raise HistoryRewriteError(
                f"branch head changed during graph rewrite: expected {expected}, found {current}"
            )
        self.source.replace_head(result.target, result.new_head)
        return replace(result, ref_updated=True)
