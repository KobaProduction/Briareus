"""Graph rewrites cannot change content, topology, or a concurrently moved ref."""

import unittest
from dataclasses import dataclass, field, replace
from typing import Literal

from modules.github.application.history import (
    AgentIdentity,
    RewriteCommand,
    RewriteHistory,
    RewriteTarget,
)
from modules.github.domain.history import GitCommit, GitIdentity, GitSignature, HistoryRewriteError

IDENTITY = AgentIdentity(
    "current_agent_app", "1", "agent", "agent[bot]", 2, "Agent", "agent@example.test"
)
OLD_AUTHOR = GitSignature("Old", "old@example.test", "2020-01-01T00:00:00Z")


def commit(sha: str, parents: tuple[str, ...] = ()) -> GitCommit:
    return GitCommit(sha, "tree-" + sha, "message-" + sha, parents, OLD_AUTHOR, OLD_AUTHOR)


@dataclass
class HistoryFixture:
    commits: dict[str, GitCommit] = field(default_factory=dict)
    confirm_head: str = "merge"
    identity_value: AgentIdentity = IDENTITY
    corrupt: Literal["tree", "message", "parents", "identity"] | None = None
    corrupt_final: bool = False
    created: list[GitCommit] = field(default_factory=list)
    updates: list[str] = field(default_factory=list)
    reads: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.commits:
            self.commits.update(
                {
                    "root": commit("root"),
                    "left": commit("left", ("root",)),
                    "right": commit("right", ("root",)),
                    "merge": commit("merge", ("left", "right")),
                }
            )

    def allowed_target(self, repository: str, branch: str) -> RewriteTarget:
        return RewriteTarget(repository.strip(), branch.strip())

    def head(self, _target: RewriteTarget, *, confirming: bool = False) -> str:
        return self.confirm_head if confirming else "merge"

    def commit(self, _target: RewriteTarget, sha: str) -> GitCommit:
        self.reads.append(sha)
        result = self.commits[sha]
        if self.corrupt_final and sha == "new-merge":
            return replace(result, tree="wrong final tree")
        return result

    def identity(self) -> AgentIdentity:
        return self.identity_value

    def create(
        self,
        _target: RewriteTarget,
        original: GitCommit,
        parents: tuple[str, ...],
        identity: GitIdentity,
        *,
        preserve_dates: bool,
    ) -> GitCommit:
        result = replace(
            original,
            sha="new-" + original.sha,
            parents=parents,
            author=GitSignature(
                identity.name, identity.email, original.author.date if preserve_dates else ""
            ),
            committer=GitSignature(
                identity.name, identity.email, original.committer.date if preserve_dates else ""
            ),
        )
        if self.corrupt == "tree":
            result = replace(result, tree="wrong")
        if self.corrupt == "message":
            result = replace(result, message="wrong")
        if self.corrupt == "parents":
            result = replace(result, parents=("wrong",))
        if self.corrupt == "identity":
            result = replace(result, author=OLD_AUTHOR)
        self.created.append(result)
        self.commits[result.sha] = result
        return result

    def replace_head(self, _target: RewriteTarget, sha: str) -> None:
        self.updates.append(sha)


class HistoryRewriteTests(unittest.TestCase):
    def test_dry_run_builds_exact_merge_topology_without_moving_ref(self) -> None:
        source = HistoryFixture()
        result = RewriteHistory(source).execute(RewriteCommand(" repo ", " branch ", "merge"))
        self.assertEqual(
            tuple(row.original.sha for row in result.plan), ("root", "left", "right", "merge")
        )
        self.assertEqual(source.created[-1].parents, ("new-left", "new-right"))
        self.assertTrue(all(row.author.date == OLD_AUTHOR.date for row in source.created))
        self.assertEqual(result.target, RewriteTarget("repo", "branch"))
        self.assertFalse(result.ref_updated)
        self.assertEqual(source.updates, [])

    def test_live_rewrite_updates_only_after_second_head_check(self) -> None:
        source = HistoryFixture()
        result = RewriteHistory(source).execute(
            RewriteCommand("repo", "branch", "merge", dry_run=False)
        )
        self.assertTrue(result.ref_updated)
        self.assertEqual(source.updates, ["new-merge"])

    def test_concurrent_ref_move_prevents_update_after_objects_are_built(self) -> None:
        source = HistoryFixture(confirm_head="someone-elses-commit")
        with self.assertRaisesRegex(HistoryRewriteError, "changed during graph rewrite"):
            RewriteHistory(source).execute(RewriteCommand("repo", "branch", "merge", dry_run=False))
        self.assertEqual(len(source.created), 4)
        self.assertEqual(source.updates, [])

    def test_cycle_or_graph_limit_fails_before_creating_objects(self) -> None:
        for source, limit in (
            (HistoryFixture(commits={"merge": commit("merge", ("merge",))}), 500),
            (HistoryFixture(), 2),
        ):
            with self.subTest(limit=limit):
                with self.assertRaises(HistoryRewriteError):
                    RewriteHistory(source).execute(
                        RewriteCommand("repo", "branch", "merge", max_commits=limit)
                    )
                self.assertEqual(source.created, [])
                self.assertEqual(source.updates, [])

    def test_provider_receipt_must_preserve_every_content_and_identity_invariant(self) -> None:
        variants: tuple[Literal["tree", "message", "parents", "identity"], ...] = (
            "tree",
            "message",
            "parents",
            "identity",
        )
        for variant in variants:
            source = HistoryFixture(corrupt=variant)
            with self.subTest(variant=variant):
                with self.assertRaises(HistoryRewriteError):
                    RewriteHistory(source).execute(
                        RewriteCommand("repo", "branch", "merge", dry_run=False)
                    )
                self.assertEqual(source.updates, [])

    def test_matching_identity_graph_reuses_all_objects_and_leaves_ref_unchanged(self) -> None:
        source = HistoryFixture()
        signature = GitSignature(IDENTITY.name, IDENTITY.email)
        source.commits = {
            sha: replace(row, author=signature, committer=signature)
            for sha, row in source.commits.items()
        }
        result = RewriteHistory(source).execute(
            RewriteCommand("repo", "branch", "merge", dry_run=False)
        )
        self.assertTrue(all(row.reused for row in result.plan))
        self.assertEqual(source.created, [])
        self.assertEqual(source.updates, [])
        self.assertEqual(result.new_head, "merge")

    def test_final_head_tree_is_rechecked_before_any_ref_change(self) -> None:
        source = HistoryFixture(corrupt_final=True)
        with self.assertRaisesRegex(HistoryRewriteError, "final tree mismatch"):
            RewriteHistory(source).execute(RewriteCommand("repo", "branch", "merge", dry_run=False))
        self.assertEqual(source.updates, [])

    def test_initial_head_or_identity_only_request_failure_cannot_create_commits(self) -> None:
        for command in (
            RewriteCommand("repo", "branch", "other"),
            RewriteCommand("repo", "branch", "merge", preserve_trees=False),
            RewriteCommand("repo", "branch", "merge", identity_source="other"),
        ):
            source = HistoryFixture()
            with self.subTest(command=command):
                with self.assertRaises(HistoryRewriteError):
                    RewriteHistory(source).execute(command)
                self.assertEqual(source.created, [])
                self.assertEqual(source.updates, [])

    def test_original_dates_can_be_omitted_without_changing_content(self) -> None:
        source = HistoryFixture()
        RewriteHistory(source).execute(
            RewriteCommand("repo", "branch", "merge", preserve_author_dates=False)
        )
        self.assertTrue(
            all(not row.author.date and not row.committer.date for row in source.created)
        )
