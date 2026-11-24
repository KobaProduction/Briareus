"""Exercise the common transport with actual disposable Git repositories."""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from briareus_git.accounts import AccountClientCache
from briareus_git.local_transport import (
    LocalGitConfig,
    authorize_checkout,
    git_output,
    local_git_path,
    push_checkout,
)

CONFIG = LocalGitConfig(
    "Test", "repository", "test-credentials", "# test-managed", ValueError, ValueError
)


class Host:
    def __init__(self, root: Path, remote: str) -> None:
        self.workspace_root = root
        self.remote = remote
        self.protected_branches = frozenset({"reserved"})
        self.credentials = Mock(
            return_value="https://fixture:fixture@example.invalid/team/repo.git"
        )

    def _local_git_path(self, destination: str) -> Path:
        return local_git_path(self.workspace_root, destination, CONFIG)

    def _git_output(self, target: Path, *args: str) -> str:
        return git_output(target, *args, config=CONFIG)

    def _git_optional_output(self, target: Path, *args: str) -> str:
        return git_output(target, *args, config=CONFIG, optional=True)

    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> dict:
        return authorize_checkout(
            self,
            CONFIG,
            repository,
            destination,
            account_id="fixture",
            remote=remote,
            expected=self.remote,
            accepted=frozenset({self.remote.removesuffix(".git")}),
            signature=lambda: {"name": "Fixture", "email": "fixture@example.invalid"},
            credential_url=self.credentials,
        )

    def push(self, *, branch: str = "main", expected_sha: str = "") -> dict:
        return push_checkout(
            self,
            CONFIG,
            "team/repo",
            "checkout",
            account_id="fixture",
            branch=branch,
            remote="origin",
            set_upstream=True,
            expected=self.remote,
            branch_guard=lambda value: value,
            expected_remote_sha=expected_sha,
        )


class SharedGitTransportTests(unittest.TestCase):
    def setUp(self) -> None:
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root = Path(temp.name)
        self.checkout = root / "checkout"
        self.checkout.mkdir()
        self.bare = root / "remote.git"
        self.host = Host(root, str(self.bare))
        self.git("init", "-b", "main")
        git_output(root, "init", "--bare", str(self.bare), config=CONFIG)
        self.git("remote", "add", "origin", str(self.bare))
        self.git("config", "--local", "core.hooksPath", str(self.checkout / ".git/hooks"))

    def git(self, *args: str) -> str:
        return self.host._git_output(self.checkout, *args)

    def test_authorization_and_real_push_with_lease(self) -> None:
        result = self.host.authorize_local_git("team/repo", "checkout")
        self.assertTrue(result["authorized"])
        credential = self.checkout / ".git" / CONFIG.credential_filename
        self.assertEqual(credential.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.git("config", "--get", "koba.test.accountId"), "fixture")
        self.git("commit", "--allow-empty", "-m", "first")
        first = self.host.push()["head"]
        self.assertEqual(
            git_output(self.bare, "rev-parse", "refs/heads/main", config=CONFIG), first
        )
        self.git("commit", "--allow-empty", "-m", "second")
        with self.assertRaises(ValueError):
            self.host.push(expected_sha="0" * 40)
        second = self.host.push(expected_sha=str(first))["head"]
        self.assertNotEqual(first, second)
        self.assertEqual(
            git_output(self.bare, "rev-parse", "refs/heads/main", config=CONFIG), second
        )

    def test_wrong_push_url_fails_before_credential_lookup(self) -> None:
        self.git("remote", "set-url", "--push", "origin", "https://example.invalid/other.git")
        with self.assertRaisesRegex(ValueError, "does not match"):
            self.host.authorize_local_git("team/repo", "checkout")
        self.host.credentials.assert_not_called()
        self.assertFalse((self.checkout / ".git" / CONFIG.credential_filename).exists())

    def test_reserved_hook_and_account_binding(self) -> None:
        self.host.authorize_local_git("team/repo", "checkout")
        hook = self.checkout / ".git/hooks/pre-push"
        blocked = subprocess.run(
            [str(hook)],
            input="HEAD 1 refs/heads/RESERVED 2\n",
            text=True,
            capture_output=True,
            check=False,
        )
        self.assertNotEqual(blocked.returncode, 0)
        self.assertIn("reserved branch denied", blocked.stderr)
        self.git("config", "--local", "koba.test.accountId", "other")
        with self.assertRaisesRegex(ValueError, "not authorized"):
            self.host.push()

    def test_foreign_hook_and_custom_hook_path_preserved(self) -> None:
        hook = self.checkout / ".git/hooks/pre-push"
        hook.write_text("#!/bin/sh\nexit 0\n")
        with self.assertRaisesRegex(ValueError, "not managed"):
            self.host.authorize_local_git("team/repo", "checkout")
        self.assertEqual(hook.read_text(), "#!/bin/sh\nexit 0\n")
        hook.unlink()
        self.git("config", "--local", "core.hooksPath", "other-hooks")
        with self.assertRaisesRegex(ValueError, "bypass"):
            self.host.authorize_local_git("team/repo", "checkout")
        self.host.credentials.assert_not_called()

    def test_cache_scope_revision_and_clear(self) -> None:
        cache = AccountClientCache[object]()
        first = cache.get("public", "same", "1", object)
        self.assertIs(cache.get("public", "same", "1", object), first)
        self.assertIsNot(cache.get("authenticated", "same", "1", object), first)
        updated = cache.get("public", "same", "2", object)
        self.assertIsNot(updated, first)
        cache.clear()
        self.assertIsNot(cache.get("public", "same", "2", object), updated)
