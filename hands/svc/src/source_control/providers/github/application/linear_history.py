"""Identity-only linear history rewrite with an exclusive first-parent boundary."""

from dataclasses import dataclass, replace

from source_control.providers.github.application._bindings import _SourceBinding
from source_control.providers.github.application.history import (
    AgentIdentity,
    GitHistory,
    RewriteCommand,
    RewriteTarget,
)
from source_control.providers.github.domain.history import (
    GitCommit,
    GitIdentity,
    HistoryRewriteError,
    LinearCommitRange,
    require_identity_only,
)


@dataclass(frozen=True, slots=True)
class LinearRewrite:
    original: GitCommit
    new_sha: str
    parent: str | None


@dataclass(frozen=True, slots=True)
class LinearHistoryResult:
    target: RewriteTarget
    command: RewriteCommand
    identity: AgentIdentity
    old_head: str
    new_head: str
    base_sha: str | None
    final_tree: str
    plan: tuple[LinearRewrite, ...]
    ref_updated: bool = False


class LinearHistoryLoader(_SourceBinding[GitHistory]):
    def load(
        self, target: RewriteTarget, head: str, base: str | None, maximum: int
    ) -> tuple[GitCommit, ...]:
        traversal = LinearCommitRange(head, base)
        for _ in range(maximum):
            if traversal.at_base():
                break
            if not traversal.accept(self.source.commit(target, traversal.current)):
                break
        else:
            raise HistoryRewriteError(
                f"rewrite range exceeds max_commits={maximum}; provide base_sha or raise the limit"
            )
        return traversal.finish()


class RewriteLinearHistory(_SourceBinding[GitHistory]):
    def rebuild(
        self,
        target: RewriteTarget,
        commits: tuple[GitCommit, ...],
        identity: GitIdentity,
        base: str | None,
        *,
        preserve_dates: bool,
    ) -> tuple[LinearRewrite, ...]:
        parent = base
        plan: list[LinearRewrite] = []
        seen: set[str] = set()
        for original in commits:
            parents = (parent,) if parent else ()
            created = self.source.create(
                target, original, parents, identity, preserve_dates=preserve_dates
            )
            created.require_rewritten(original, parents, identity)
            seen.add(original.sha)
            plan.append(LinearRewrite(original, created.sha, parent))
            parent = created.sha
        if len(seen) != len(commits):
            raise HistoryRewriteError("rewritten commit count does not match source commit count")
        return tuple(plan)

    def execute(self, command: RewriteCommand, base: str | None) -> LinearHistoryResult:
        target = self.source.allowed_target(command.repository, command.branch)
        require_identity_only(
            command.expected_head_sha,
            command.identity_source,
            preserve_messages=command.preserve_messages,
            preserve_trees=command.preserve_trees,
        )
        old_head = self.source.head(target)
        if old_head != command.expected_head_sha:
            raise HistoryRewriteError(
                f"branch head changed: expected {command.expected_head_sha}, found {old_head}"
            )
        commits = LinearHistoryLoader(self.source).load(
            target, old_head, base, max(1, min(command.max_commits, 500))
        )
        identity = self.source.identity()
        plan = self.rebuild(
            target, commits, identity.git, base, preserve_dates=command.preserve_author_dates
        )
        final = self.source.commit(target, plan[-1].new_sha)
        if not commits[-1].tree or final.tree != commits[-1].tree:
            raise HistoryRewriteError(
                f"final tree mismatch: expected {commits[-1].tree}, found {final.tree}"
            )
        result = LinearHistoryResult(
            target, command, identity, old_head, plan[-1].new_sha, base, final.tree, plan
        )
        return self.update_ref(result)

    def update_ref(self, result: LinearHistoryResult) -> LinearHistoryResult:
        if result.command.dry_run:
            return result
        current = self.source.head(result.target, confirming=True)
        if current != result.command.expected_head_sha:
            raise HistoryRewriteError(
                "branch head changed during rewrite: "
                f"expected {result.command.expected_head_sha}, found {current}"
            )
        self.source.replace_head(result.target, result.new_head)
        return replace(result, ref_updated=True)
