from __future__ import annotations

import unittest
from typing import cast

from briareus_github.github_actions import GitHubActionsClient
from briareus_github.github_agent import GitHubAgentError
from briareus_github.github_history import GitHubHistoryMixin
from briareus_github.github_history_graph import rewrite_branch_identity_graph
from briareus_json_values import JsonContainer, JsonObject, json_member_array, json_member_object


def commit(sha: str, parents: list[str], *, current_identity: bool = False) -> JsonObject:
    name = "Agent" if current_identity else "Original"
    email = "agent@example.test" if current_identity else "original@example.test"
    return {
        "sha": sha,
        "tree": {"sha": f"tree-{sha}"},
        "message": f"message-{sha}",
        "parents": [{"sha": parent} for parent in parents],
        "author": {"name": name, "email": email, "date": "2026-01-01T00:00:00Z"},
        "committer": {"name": name, "email": email, "date": "2026-01-02T00:00:00Z"},
    }


class HistoryBackend(GitHubHistoryMixin):
    def __init__(self, commits: list[JsonObject], head: str) -> None:
        self.commits = {str(item["sha"]): item for item in commits}
        self.head = head
        self.created: list[JsonObject] = []
        self.updates: list[JsonObject] = []
        self.head_reads = 0
        self.change_head_before_update = False
        self.corrupt_created_tree = False

    def _assert_allowed(self, repository: str) -> str:
        return repository

    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str:
        del repository
        return branch

    def _agent_app_identity(self) -> JsonObject:
        return {"name": "Agent", "email": "agent@example.test"}

    def _git_commit_object(self, repository: str, sha: str) -> JsonObject:
        del repository
        return self.commits[sha]

    def _repo_request(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: object | None = None,
        allowed_errors: set[int] | None = None,
    ) -> tuple[int, JsonContainer]:
        del repository, allowed_errors
        if method == "GET" and "/git/ref/heads/" in path:
            self.head_reads += 1
            head = (
                "concurrent-head"
                if self.change_head_before_update and self.head_reads > 1
                else self.head
            )
            return 200, {"object": {"sha": head}}
        if method == "POST" and path.endswith("/git/commits"):
            assert isinstance(payload, dict)
            created = cast(JsonObject, dict(payload))
            created["sha"] = f"new-{len(self.created)}"
            created["tree"] = {"sha": "corrupt" if self.corrupt_created_tree else payload["tree"]}
            created["parents"] = [{"sha": sha} for sha in json_member_array(created, "parents")]
            self.commits[str(created["sha"])] = created
            self.created.append(created)
            return 201, created
        if method == "PATCH":
            assert isinstance(payload, dict)
            self.updates.append(cast(JsonObject, payload))
            return 200, {}
        raise AssertionError(f"unexpected request: {method} {path}")


class GitHistoryIntegrityContracts(unittest.TestCase):
    def test_linear_dry_run_preserves_content_dates_and_parent_chain(self) -> None:
        backend = HistoryBackend([commit("root", []), commit("head", ["root"])], "head")
        result = backend.rewrite_branch_identity("owner/repo", "feature", "head")
        self.assertEqual(result["commit_count"], 2)
        self.assertEqual(result["final_tree_sha"], "tree-head")
        self.assertTrue(result["dry_run_creates_unreferenced_commit_objects"])
        self.assertEqual(backend.updates, [])
        first, second = backend.created
        self.assertEqual(json_member_array(first, "parents"), [])
        self.assertEqual(json_member_array(second, "parents"), [{"sha": first["sha"]}])
        self.assertEqual(second["message"], "message-head")
        self.assertEqual(json_member_object(second, "author")["date"], "2026-01-01T00:00:00Z")
        self.assertEqual(json_member_object(second, "committer")["date"], "2026-01-02T00:00:00Z")

    def test_linear_merge_and_changed_tree_never_update_ref(self) -> None:
        merge = HistoryBackend([commit("head", ["left", "right"])], "head")
        with self.assertRaisesRegex(GitHubAgentError, "linear history only"):
            merge.rewrite_branch_identity("owner/repo", "feature", "head", dry_run=False)
        self.assertEqual(merge.created, [])
        corrupt = HistoryBackend([commit("head", [])], "head")
        corrupt.corrupt_created_tree = True
        with self.assertRaisesRegex(GitHubAgentError, "tree mismatch"):
            corrupt.rewrite_branch_identity("owner/repo", "feature", "head", dry_run=False)
        self.assertEqual(corrupt.updates, [])

    def test_graph_preserves_merge_topology_and_reuses_unchanged_ancestor(self) -> None:
        backend = HistoryBackend(
            [
                commit("root", [], current_identity=True),
                commit("left", ["root"]),
                commit("right", ["root"]),
                commit("head", ["left", "right"]),
            ],
            "head",
        )
        result = rewrite_branch_identity_graph(
            cast(GitHubActionsClient, backend), "owner/repo", "feature", "head", dry_run=False
        )
        self.assertEqual(result["merge_commit_count"], 1)
        self.assertEqual(result["reused_commit_count"], 1)
        self.assertEqual(result["rewritten_commit_count"], 3)
        self.assertEqual(
            json_member_array(backend.created[-1], "parents"), [{"sha": "new-0"}, {"sha": "new-1"}]
        )
        self.assertEqual(backend.updates, [{"sha": "new-2", "force": True}])

    def test_compare_and_swap_rejects_concurrent_update_in_both_rewriters(self) -> None:
        for graph in (False, True):
            with self.subTest(graph=graph):
                backend = HistoryBackend([commit("head", [])], "head")
                backend.change_head_before_update = True
                with self.assertRaisesRegex(GitHubAgentError, "branch head changed during"):
                    if graph:
                        rewrite_branch_identity_graph(
                            cast(GitHubActionsClient, backend),
                            "owner/repo",
                            "feature",
                            "head",
                            dry_run=False,
                        )
                    else:
                        backend.rewrite_branch_identity(
                            "owner/repo", "feature", "head", dry_run=False
                        )
                self.assertEqual(backend.updates, [])
