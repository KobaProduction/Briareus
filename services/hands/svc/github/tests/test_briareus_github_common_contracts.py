from __future__ import annotations

import unittest
from unittest.mock import patch

from briareus_github.github_agent import GitHubAgentError
from briareus_github.github_identity import GitHubPrettyIdentityClient

REPO = "team/repo"


class GitHubCommonContracts(unittest.TestCase):
    def client(self) -> GitHubPrettyIdentityClient:
        return GitHubPrettyIdentityClient(
            app_id="",
            private_key="",
            token="test-only",
            auth_type="github_token",
            account_id="test-account",
        )

    def test_review_cursor_and_native_ci_routes(self) -> None:
        client = self.client()
        page = {
            "repository": {
                "pullRequest": {
                    "reviewThreads": {
                        "nodes": [
                            {
                                "id": "thread",
                                "comments": {
                                    "nodes": [],
                                    "pageInfo": {"hasNextPage": True},
                                },
                            }
                        ],
                        "pageInfo": {"hasNextPage": True, "endCursor": "next"},
                    }
                }
            }
        }
        with patch.object(client, "_graphql", return_value=page) as graphql:
            result = client.list_review_threads(REPO, 7, 20, "previous")
            self.assertEqual(result["next_cursor"], "next")
            self.assertEqual(graphql.call_args.args[2]["after"], "previous")
            self.assertEqual(graphql.call_args.args[2]["first"], 20)
            self.assertIn("comments_truncated", str(result["threads"]))
        with patch.object(client, "_repo_request", return_value=(202, {})) as request:
            client.retry_incomplete_run(REPO, 11)
            request.assert_called_with(
                REPO, "POST", f"/repos/{REPO}/actions/runs/11/rerun-failed-jobs"
            )
            client.cancel_run(REPO, 11)
            request.assert_called_with(REPO, "POST", f"/repos/{REPO}/actions/runs/11/cancel")

    def test_review_mutation_cannot_cross_repository_or_pull_request(self) -> None:
        client = self.client()
        for repo, number in (("other/repo", 7), (REPO, 8)):
            with (
                self.subTest(repo=repo, number=number),
                patch.object(
                    client,
                    "_graphql",
                    return_value={
                        "node": {
                            "id": "thread",
                            "repository": {"nameWithOwner": repo},
                            "pullRequest": {"number": number},
                        }
                    },
                ) as graphql,
            ):
                with self.assertRaisesRegex(GitHubAgentError, "does not belong"):
                    client.set_review_thread_resolved(REPO, 7, "thread", True)
                graphql.assert_called_once()
        with patch.object(
            client,
            "_graphql",
            side_effect=[
                {
                    "node": {
                        "id": "thread",
                        "repository": {"nameWithOwner": REPO},
                        "pullRequest": {"number": 7},
                    }
                },
                {"resolveReviewThread": {"thread": {"id": "thread", "isResolved": True}}},
            ],
        ) as graphql:
            result = client.set_review_thread_resolved(REPO, 7, "thread", True)
            self.assertTrue(result["resolved"])
            self.assertEqual(graphql.call_count, 2)
