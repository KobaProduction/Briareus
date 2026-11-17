"""Verify exact upstream dependency routing and Git history validation."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from scripts.ai_agent_workflow_dispatch import changed_files, classify_paths, write_github_output


class RoutingContracts(unittest.TestCase):
    def test_git_workflow_changes_affect_only_git_hands(self) -> None:
        for path in (
            "skills/git-workflow.md", "skills/git-workflow/publication.md",
            "skills/orchestration/communication.md", "docs/REPORTING_PROTOCOL.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify_paths([path]), {
                    "github": True, "gitlab": True, "coolify": False, "any": True,
                })

    def test_deployment_changes_affect_only_coolify(self) -> None:
        for path in (
            "skills/services-deployment/README.md",
            "skills/services-deployment/coolify-compose.md",
            "skills/terminal-operations.md", "docs/MCP_STRATEGY.md",
        ):
            with self.subTest(path=path):
                self.assertEqual(classify_paths([path]), {
                    "github": False, "gitlab": False, "coolify": True, "any": True,
                })

    def test_global_or_unrelated_changes_and_unknown_old_commit(self) -> None:
        self.assertTrue(all(classify_paths(["AGENTS.md"]).values()))
        self.assertFalse(any(classify_paths(["README.md", "audit/README.md"]).values()))
        self.assertTrue(all(classify_paths([], full=True).values()))

    def test_github_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "output"
            path.touch()
            write_github_output(path, classify_paths(["skills/git-workflow.md"]))
            self.assertEqual(
                path.read_text(),
                "github=true\ngitlab=true\ncoolify=false\nany=true\n",
            )

    def test_comparison_checks_real_upstream_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            subprocess.run(["git", "init", "-b", "main", str(root)],
                           check=True, capture_output=True)
            for key, value in (("user.name", "Tester"), ("user.email", "test@example.test")):
                subprocess.run(["git", "-C", str(root), "config", key, value], check=True)
            (root / "README.md").write_text("initial")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "initial"],
                           check=True, capture_output=True)
            previous = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            (root / "skills").mkdir()
            (root / "skills/git-workflow.md").write_text("changed")
            subprocess.run(["git", "-C", str(root), "add", "."], check=True)
            subprocess.run(["git", "-C", str(root), "commit", "-m", "change"],
                           check=True, capture_output=True)
            current = subprocess.check_output(
                ["git", "-C", str(root), "rev-parse", "HEAD"], text=True
            ).strip()
            subprocess.run(
                ["git", "-C", str(root), "update-ref", "refs/remotes/origin/main", current],
                check=True,
            )
            self.assertEqual(changed_files(root, previous, current),
                             (["skills/git-workflow.md"], False))
            self.assertEqual(changed_files(root, current, current), ([], False))
            self.assertEqual(changed_files(root, "0" * 40, current), ([], True))
            with self.assertRaisesRegex(ValueError, "40-character"):
                changed_files(root, "invalid", current)
