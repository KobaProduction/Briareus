"""Linear history retains its exclusive boundary and rejects corrupted provider receipts."""

import unittest
from dataclasses import dataclass

from modules.github.application.history import RewriteCommand, RewriteTarget
from modules.github.application.linear_history import RewriteLinearHistory
from modules.github.domain.history import HistoryRewriteError
from modules.github.tests.test_history_rewrite import HistoryFixture


@dataclass
class LinearFixture(HistoryFixture):
    confirm_head: str = "left"

    def head(self, _target: RewriteTarget, *, confirming: bool = False) -> str:
        return self.confirm_head if confirming else "left"


class LinearHistoryTests(unittest.TestCase):
    def test_exclusive_base_preserves_parent_and_dates(self) -> None:
        source = LinearFixture()
        result = RewriteLinearHistory(source).execute(
            RewriteCommand("repo", "branch", "left"), "root"
        )
        self.assertEqual(len(result.plan), 1)
        self.assertEqual(result.plan[0].parent, "root")
        self.assertEqual(source.created[0].parents, ("root",))
        self.assertEqual(source.created[0].author.date, result.plan[0].original.author.date)
        self.assertFalse(result.ref_updated)
        self.assertEqual(source.updates, [])

    def test_complete_chain_updates_once(self) -> None:
        source = LinearFixture()
        result = RewriteLinearHistory(source).execute(
            RewriteCommand("repo", "branch", "left", dry_run=False), None
        )
        self.assertEqual([item.original.sha for item in result.plan], ["root", "left"])
        self.assertEqual(source.created[1].parents, ("new-root",))
        self.assertTrue(result.ref_updated)
        self.assertEqual(source.updates, ["new-left"])

    def test_concurrent_head_change_prevents_update(self) -> None:
        source = LinearFixture(confirm_head="other")
        with self.assertRaisesRegex(HistoryRewriteError, "branch head changed during rewrite"):
            RewriteLinearHistory(source).execute(
                RewriteCommand("repo", "branch", "left", dry_run=False), None
            )
        self.assertEqual(source.updates, [])

    def test_bad_parent_receipt_prevents_update(self) -> None:
        source = LinearFixture(corrupt="parents")
        with self.assertRaisesRegex(HistoryRewriteError, "parent topology mismatch"):
            RewriteLinearHistory(source).execute(
                RewriteCommand("repo", "branch", "left", dry_run=False), None
            )
        self.assertEqual(source.updates, [])

    def test_unreachable_base_prevents_creation(self) -> None:
        source = LinearFixture()
        with self.assertRaisesRegex(HistoryRewriteError, "not a first-parent ancestor"):
            RewriteLinearHistory(source).execute(RewriteCommand("repo", "branch", "left"), "other")
        self.assertEqual(source.created, [])

    def test_merge_is_rejected_before_creation(self) -> None:
        source = HistoryFixture()
        with self.assertRaisesRegex(HistoryRewriteError, "linear history only"):
            RewriteLinearHistory(source).execute(RewriteCommand("repo", "branch", "merge"), None)
        self.assertEqual(source.created, [])

    def test_empty_range_is_rejected(self) -> None:
        source = LinearFixture()
        with self.assertRaisesRegex(HistoryRewriteError, "contains no commits"):
            RewriteLinearHistory(source).execute(RewriteCommand("repo", "branch", "left"), "left")
        self.assertEqual(source.created, [])
