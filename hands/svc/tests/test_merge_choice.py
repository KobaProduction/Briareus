"""Explicit source-branch intent survives PR creation, edits and reviewer handoff."""
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from common.merge_policy import branch_choice, with_branch_choice
from modules.github.pulls import GitHubPullClient
from modules.gitlab.merge_requests import GitLabMergeRequestClient
from modules.gitlab.errors import GitLabError


class MergeChoiceTests(unittest.TestCase):
    def test_marker_replaces_old_choice_without_changing_description(self):
        self.assertEqual(branch_choice(with_branch_choice("Description", False)), False)
        self.assertEqual(branch_choice(with_branch_choice(with_branch_choice("Description", False), True)), True)
        with self.assertRaises(ValueError):
            with_branch_choice("body", None)

    def test_github_create_persists_choice_and_read_exposes_it(self):
        client = object.__new__(GitHubPullClient)
        def request(repository, method, path, **kwargs):
            payload = kwargs["payload"]
            self.assertEqual(branch_choice(payload["body"]), True)
            self.assertTrue(payload["body"].startswith("Description"))
            return 201, {"number": 1, **payload}
        with patch.object(client, "_assert_allowed", side_effect=lambda repo: repo), patch.object(client, "_repo_request", side_effect=request):
            result = client.create_pull_request("owner/repo", "Title", "feature", "main", True, "Description")
        self.assertIs(result["pull_request"]["delete_source_branch_after_merge"], True)
        with self.assertRaises(ValueError):
            client.create_pull_request("owner/repo", "Title", "feature", "main", None)

    def test_github_description_edit_preserves_provider_choice(self):
        client = object.__new__(GitHubPullClient)
        with patch.object(client, "_assert_allowed", side_effect=lambda repo: repo), patch.object(client, "_repo_request", side_effect=[
            (200, {"body": with_branch_choice("old", False)}), (200, {"number": 1})]) as request:
            client.update_pull_request("owner/repo", 1, body="New description")
        self.assertIs(branch_choice(request.call_args.kwargs["payload"]["body"]), False)
        self.assertTrue(request.call_args.kwargs["payload"]["body"].startswith("New description"))

    def test_gitlab_create_uses_same_required_choice_and_native_storage(self):
        client = object.__new__(GitLabMergeRequestClient)
        client.profile = SimpleNamespace(profile_id="fixture")
        with patch.object(client, "request", return_value=SimpleNamespace(data={"iid": 1})) as request:
            client.create_merge_request("owner/repo", "feature", "main", "Title", False)
        self.assertIs(request.call_args.kwargs["payload"]["remove_source_branch"], False)
        with self.assertRaises(GitLabError):
            client.create_merge_request("owner/repo", "feature", "main", "Title", None)


if __name__ == "__main__":
    unittest.main()
