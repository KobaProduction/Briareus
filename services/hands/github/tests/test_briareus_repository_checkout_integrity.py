from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from briareus_git.repository_checkout import RepositoryCheckoutError, checkout_repository


class CheckoutIntegrityContracts(unittest.TestCase):
    def test_failed_authenticated_attempt_cleans_partial_clone_before_anonymous_fallback(
        self,
    ) -> None:
        attempts: list[tuple[Path, bool]] = []

        def clone(command: list[str], *, env: dict[str, str], timeout_seconds: int) -> None:
            self.assertEqual(timeout_seconds, 300)
            self.assertEqual(env["GIT_TERMINAL_PROMPT"], "0")
            target = Path(command[-1])
            authenticated = "GIT_CONFIG_VALUE_0" in env
            attempts.append((target, authenticated))
            target.mkdir()
            (target / ".git").mkdir()
            (target / "file.txt").write_text("checkout", encoding="utf-8")
            if authenticated:
                raise RepositoryCheckoutError("authenticated clone rejected")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("briareus_git.repository_checkout._run", side_effect=clone):
                result = checkout_repository(
                    "https://example.test/repository.git",
                    "project",
                    workspace_root=root,
                    auth_scope="https://example.test/",
                    auth_header="test-authorization",
                    fallback_without_auth=True,
                )
            self.assertEqual(result["auth_mode"], "anonymous_fallback")
            self.assertEqual((root / "project/file.txt").read_text(encoding="utf-8"), "checkout")
            self.assertFalse((root / "project/.git").exists())
            self.assertEqual([authorized for _, authorized in attempts], [True, False])
            self.assertTrue(all(not target.exists() for target, _ in attempts))
            self.assertEqual([path.name for path in root.iterdir()], ["project"])

    def test_failed_clone_without_fallback_leaves_no_partial_destination(self) -> None:
        def fail(command: list[str], *, env: dict[str, str], timeout_seconds: int) -> None:
            del env, timeout_seconds
            Path(command[-1]).mkdir()
            raise RepositoryCheckoutError("offline")

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with (
                patch("briareus_git.repository_checkout._run", side_effect=fail),
                self.assertRaisesRegex(RepositoryCheckoutError, "offline"),
            ):
                checkout_repository("https://example.test/repo.git", "project", workspace_root=root)
            self.assertEqual(list(root.iterdir()), [])
