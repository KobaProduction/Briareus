from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from common.settings import GitHubPolicySettings, GitLabSettings
from modules.github.github_identity import GitHubPrettyIdentityClient
from modules.github.refs import GitHubRefsClient
from modules.gitlab.models import GitLabProfile
from modules.gitlab.policy import require_mutable_branch
from modules.gitlab.repository import GitLabRepositoryClient
from service_runtime.http_transport import HttpTransportResponse
from source_control.providers.gitlab.local_git_views import GitLabGitPush


class DirectPushPolicyTests(unittest.TestCase):
    def test_empty_defaults_and_explicit_overrides(self) -> None:
        self.assertEqual(GitHubPolicySettings().protected_branches, frozenset())
        self.assertEqual(GitLabSettings().protected_branches, frozenset())
        self.assertEqual(
            GitHubPolicySettings.model_validate(
                {"GITHUB_AGENT_PROTECTED_BRANCHES": "main,MASTER"},
            ).protected_branches,
            frozenset({"main", "master"}),
        )
        self.assertEqual(require_mutable_branch("main", frozenset()), "main")

    def test_github_protected_flag_is_informational(self) -> None:
        client = GitHubRefsClient(protected_branches=frozenset())
        response = HttpTransportResponse(
            status=200,
            headers={},
            will_close=False,
            body=b'{"name":"main","protected":true,"commit":{"sha":"head"}}',
        )
        with patch.object(client, "_repo_transport", return_value=response):
            policy = client._branch_policy("org/repo", "main")
            self.assertTrue(policy.github_protected)
            self.assertTrue(policy.mutation_allowed)
            client.protected_branches = frozenset({"main"})
            policy = client._branch_policy("org/repo", "main")
            self.assertFalse(policy.mutation_allowed)

    def test_github_push_removes_only_old_managed_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "checkout"
            hook = repo / ".git" / "hooks" / "pre-push"
            hook.parent.mkdir(parents=True)
            hook.write_text(
                "#!/bin/sh\n# koba-managed-local-git-guard\nexit 1\n",
                encoding="utf-8",
            )

            def git(*args: str) -> str:
                if args[0] == "branch":
                    return "main"
                if args[0] == "push":
                    self.assertFalse(hook.exists())
                    return "ok"
                if args[0] == "rev-parse":
                    return "a" * 40
                return ""

            values = {
                "koba.github.repository": "org/repo",
                "koba.github.accountId": "agent",
                "koba.github.transportAuthorized": "true",
            }
            client = GitHubPrettyIdentityClient(
                account_id="agent", workspace_root=root, protected_branches=frozenset()
            )

            def optional_output(path: Path, *args: str) -> str:
                self.assertEqual(path, repo)
                return values.get(args[-1], "")

            def output(path: Path, *args: str) -> str:
                self.assertEqual(path, repo)
                return git(*args)

            with (
                patch.object(client, "_local_git_path", return_value=repo),
                patch.object(client, "_git_optional_output", side_effect=optional_output),
                patch.object(client, "_git_output", side_effect=output),
                patch.object(client, "_assert_branch_mutation_allowed", return_value="main"),
            ):
                result = client.push_local_git("org/repo", "checkout")
            self.assertTrue(result.pushed)

    def test_gitlab_push_keeps_unmanaged_hook(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            repo = root / "checkout"
            hook = repo / ".git" / "hooks" / "pre-push"
            hook.parent.mkdir(parents=True)
            hook.write_text("#!/bin/sh\n# owner custom hook\nexit 0\n", encoding="utf-8")
            values = {
                "koba.gitlab.project": "team/repo",
                "koba.gitlab.accountId": "agent",
                "koba.gitlab.transportAuthorized": "true",
            }

            def git(*args: str) -> str:
                if args[0] == "branch":
                    return "main"
                if args[0] == "push":
                    self.assertTrue(hook.exists())
                    return "ok"
                if args[0] == "rev-parse":
                    return "a" * 40
                return ""

            client = GitLabRepositoryClient(
                GitLabProfile(
                    account_id="agent",
                    alias="agent",
                    base_url="https://gitlab.test",
                    auth_type="private_token",
                ),
                workspace_root=root,
            )

            def optional_output(path: Path, *args: str) -> str:
                self.assertEqual(path, repo)
                return values.get(args[-1], "")

            def output(path: Path, *args: str) -> str:
                self.assertEqual(path, repo)
                return git(*args)

            with (
                patch.object(client, "_local_git_path", return_value=repo),
                patch.object(client, "_git_optional_output", side_effect=optional_output),
                patch.object(client, "_git_output", side_effect=output),
            ):
                result = client.push_local_git("team/repo", "checkout")
            assert isinstance(result, GitLabGitPush)
            self.assertTrue(result.pushed)


if __name__ == "__main__":
    unittest.main()
