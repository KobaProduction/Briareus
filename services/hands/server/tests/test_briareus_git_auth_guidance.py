from __future__ import annotations

import unittest

from briareus_json_values import JsonObject
from briareus_server.terminal.git_guidance import with_git_auth_guidance


class GitAuthGuidanceTests(unittest.TestCase):
    def test_failed_git_auth_names_both_provider_tools_and_exact_arguments(self) -> None:
        for error in (
            "fatal: could not read Username for 'https://github.com': terminal prompts disabled",
            "fatal: Authentication failed for 'https://git.example.test/group/repo.git/'",
            "remote: HTTP Basic: Access denied",
            "git@github.com: Permission denied (publickey).",
        ):
            with self.subTest(error=error):
                result: JsonObject = {"exit_code": 128, "stdout": "", "stderr": error}
                updated = with_git_auth_guidance(result)
                self.assertEqual(updated["stderr"], error)
                hint = updated["git_auth_hint"]
                assert isinstance(hint, dict)
                self.assertIn("github_authorize_local_git", str(hint["github"]))
                self.assertIn("authorize_local_git", str(hint["gitlab"]))
                self.assertIn("repository", str(hint["github"]))
                self.assertIn("project", str(hint["gitlab"]))
                self.assertIn("destination", str(hint))
                self.assertNotIn("git_auth_hint", result)

    def test_network_branch_and_other_failures_do_not_claim_an_auth_problem(self) -> None:
        for error in (
            "fatal: unable to access remote: Connection reset by peer",
            "fatal: Could not resolve host: github.com",
            "remote: protected branch hook declined",
            "fatal: repository not found",
            "npm ERR! Authentication failed",
        ):
            result: JsonObject = {"exit_code": 1, "stderr": error}
            self.assertIs(with_git_auth_guidance(result), result)

    def test_success_timeout_and_running_job_do_not_trigger_recovery(self) -> None:
        for result in (
            {"exit_code": 0, "stderr": "fatal: Authentication failed"},
            {"exit_code": 128, "timed_out": True, "stderr": "fatal: Authentication failed"},
            {"state": "running", "output": "fatal: Authentication failed"},
        ):
            data: JsonObject = result
            self.assertIs(with_git_auth_guidance(data), data)

    def test_retained_failed_job_gets_the_same_hint_without_copying_secret_output(self) -> None:
        result: JsonObject = {
            "state": "failed", "output": "fatal: Authentication failed private-fixture-token",
        }
        updated = with_git_auth_guidance(result)
        self.assertNotIn("private-fixture-token", str(updated["git_auth_hint"]))
        self.assertEqual(updated["output"], result["output"])
