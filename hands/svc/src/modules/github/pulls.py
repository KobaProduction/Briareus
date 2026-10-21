from __future__ import annotations

import urllib.parse
from common.merge_policy import branch_choice, with_branch_choice

from common.models import (
    JsonObject,
    json_array,
    json_bool,
    json_int,
    json_member_array,
    json_member_object,
    json_str,
)

from .base import GitHubRepositoryClientBase
from .github_agent import GitHubAgentError


class GitHubPullClient(GitHubRepositoryClientBase):
    def list_pull_requests(
        self,
        repository: str,
        state: str = "open",
        per_page: int = 50,
        page: int = 1,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if state not in {"open", "closed", "all"}:
            raise GitHubAgentError("state must be open, closed, or all")
        params = urllib.parse.urlencode(
            {
                "state": state,
                "per_page": max(1, min(per_page, 100)),
                "page": max(1, page),
            }
        )
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls?{params}",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request list response")
        return {
            "repository": repository,
            "pull_requests": [
                self._compact_pull(item)
                for item in result
                if isinstance(item, dict)
            ],
            "page": page,
        }

    @staticmethod
    def _compact_pull(item: JsonObject) -> JsonObject:
        head = json_member_object(item, "head")
        base = json_member_object(item, "base")
        return {
            "number": json_int(item.get("number")),
            "title": json_str(item.get("title")),
            "state": json_str(item.get("state")),
            "draft": json_bool(item.get("draft")),
            "head": json_str(head.get("ref")),
            "head_sha": json_str(head.get("sha")),
            "base": json_str(base.get("ref")),
            "merged": json_bool(item.get("merged")),
            "html_url": json_str(item.get("html_url")),
            "delete_source_branch_after_merge": branch_choice(json_str(item.get("body"))),
        }

    def get_pull_request(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request response")
        compact = self._compact_pull(result)
        compact["body"] = json_str(result.get("body"))
        compact["mergeable"] = result.get("mergeable")
        compact["mergeable_state"] = json_str(result.get("mergeable_state"))
        return {"repository": repository, "pull_request": compact}

    def create_pull_request(
        self,
        repository: str,
        title: str,
        head: str,
        base: str,
        delete_source_branch_after_merge: bool,
        body: str = "",
        draft: bool = False,
    ) -> JsonObject:
        body = with_branch_choice(body, delete_source_branch_after_merge)
        repository = self._assert_allowed(repository)
        if ":" in head or ":" in base:
            raise GitHubAgentError("cross-repository pull requests are disabled")
        if head == base:
            raise GitHubAgentError("pull request head and base must differ")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls",
            payload={
                "title": title,
                "head": head,
                "base": base,
                "body": body,
                "draft": draft,
            },
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request create response")
        return {"repository": repository, "pull_request": self._compact_pull(result)}

    def update_pull_request(
        self,
        repository: str,
        number: int,
        title: str | None = None,
        body: str | None = None,
        state: str | None = None,
        base: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        payload: JsonObject = {}
        if title is not None:
            payload["title"] = title
        if body is not None:
            # Editing the description must not silently discard the workflow's
            # provider-persisted choice, including across reviewer identities.
            _, current = self._repo_request(repository, "GET", f"/repos/{repository}/pulls/{number}")
            choice = branch_choice(json_str(current.get("body"))) if isinstance(current, dict) else None
            payload["body"] = with_branch_choice(body, choice) if choice is not None else body
        if state is not None:
            if state not in {"open", "closed"}:
                raise GitHubAgentError("state must be open or closed")
            payload["state"] = state
        if base is not None:
            if ":" in base:
                raise GitHubAgentError("cross-repository pull requests are disabled")
            payload["base"] = base
        if not payload:
            raise GitHubAgentError("no pull request fields were supplied")
        _, result = self._repo_request(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/{number}",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request update response")
        return {"repository": repository, "pull_request": self._compact_pull(result)}

    def list_pull_files(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/files?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request file response")
        files = [
            {
                "filename": json_str(item.get("filename")),
                "status": json_str(item.get("status")),
                "additions": json_int(item.get("additions")),
                "deletions": json_int(item.get("deletions")),
                "patch": item.get("patch"),
            }
            for item in result
            if isinstance(item, dict)
        ]
        return {
            "repository": repository,
            "number": number,
            "files": json_array(files, context="GitHub pull files"),
        }

    def add_pull_comment(
        self,
        repository: str,
        number: int,
        body: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/issues/{number}/comments",
            payload={"body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request comment response")
        return {
            "repository": repository,
            "number": number,
            "comment_id": json_int(result.get("id")),
            "html_url": json_str(result.get("html_url")),
        }

    def list_reviews(self, repository: str, number: int) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}/reviews?per_page=100",
        )
        if not isinstance(result, list):
            raise GitHubAgentError("unexpected pull request review response")
        reviews = []
        for item in result:
            if not isinstance(item, dict):
                continue
            user = json_member_object(item, "user")
            reviews.append(
                {
                    "id": json_int(item.get("id")),
                    "user": json_str(user.get("login")),
                    "state": json_str(item.get("state")),
                    "body": json_str(item.get("body")),
                    "submitted_at": json_str(item.get("submitted_at")),
                }
            )
        return {
            "repository": repository,
            "number": number,
            "reviews": json_array(reviews, context="GitHub reviews"),
        }

    def create_review(
        self,
        repository: str,
        number: int,
        event: str,
        body: str,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        event = event.upper()
        if event not in {"APPROVE", "REQUEST_CHANGES", "COMMENT"}:
            raise GitHubAgentError("event must be APPROVE, REQUEST_CHANGES, or COMMENT")
        _, result = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/pulls/{number}/reviews",
            payload={"event": event, "body": body},
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected review create response")
        return {
            "repository": repository,
            "number": number,
            "review_id": json_int(result.get("id")),
            "state": json_str(result.get("state")),
        }

    def update_pull_branch(
        self,
        repository: str,
        number: int,
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        payload: JsonObject = {}
        if expected_head_sha:
            payload["expected_head_sha"] = expected_head_sha
        _, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/update-branch",
            payload=payload,
        )
        return {"repository": repository, "number": number, "result": result}

    def check_runs(self, repository: str, ref: str) -> JsonObject:
        repository = self._assert_allowed(repository)
        _, result = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}/check-runs?per_page=100",
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected check-run response")
        raw = json_member_array(result, "check_runs")
        checks = []
        for item in raw:
            if isinstance(item, dict):
                app = json_member_object(item, "app")
                checks.append(
                    {
                        "name": json_str(item.get("name")),
                        "status": json_str(item.get("status")),
                        "conclusion": item.get("conclusion"),
                        "app": json_str(app.get("slug")),
                        "details_url": json_str(item.get("details_url")),
                    }
                )
        return {
            "repository": repository,
            "ref": ref,
            "check_runs": json_array(checks, context="GitHub check runs"),
        }

    def assert_required_checks(self, repository: str, ref: str) -> JsonObject:
        result = self.check_runs(repository, ref)
        checks = result["check_runs"]
        assert isinstance(checks, list)
        by_name = {
            json_str(item.get("name")): item
            for item in checks
            if isinstance(item, dict)
        }
        required = list(self.required_checks)

        # The bridge can serve multiple repositories whose CI check names are
        # unrelated. GITHUB_AGENT_REQUIRED_CHECKS is therefore only applicable
        # when at least one configured check name is part of this repository's
        # normal CI surface. If the PR head has none of them, inspect the
        # repository's default branch before deciding that they are "missing".
        #
        # This keeps the strict test/docker gate for mcp-bridge while
        # avoiding an impossible merge requirement on repositories such as
        # ghidra-mcp, whose aggregate check is named "Build Status". GitHub's
        # own branch protection/rulesets remain the final merge authority.
        def matches(required_name: str, checks_by_name: dict[str, JsonObject]) -> list[JsonObject]:
            exact = checks_by_name.get(required_name)
            if exact is not None:
                return [exact]
            matrix_prefix = f"{required_name} ("
            return [
                item
                for name, item in checks_by_name.items()
                if name.startswith(matrix_prefix)
            ]

        if required and not any(matches(name, by_name) for name in required):
            repository_info = self._repository_metadata(repository)
            default_branch = json_str(repository_info.get("default_branch"))
            baseline_by_name: dict[str, JsonObject] = {}
            if default_branch:
                baseline = self.check_runs(repository, default_branch)
                baseline_checks = baseline["check_runs"]
                assert isinstance(baseline_checks, list)
                baseline_by_name = {
                    json_str(item.get("name")): item
                    for item in baseline_checks
                    if isinstance(item, dict)
                }
            if not any(matches(name, baseline_by_name) for name in required):
                return {
                    "repository": repository,
                    "ref": ref,
                    "required": json_array(required, context="GitHub required checks"),
                    "status": "delegated_to_github",
                }

        missing = [name for name in required if not matches(name, by_name)]
        failing = [
            name
            for name in required
            if any(
                item.get("status") != "completed"
                or item.get("conclusion") != "success"
                for item in matches(name, by_name)
            )
        ]
        if missing or failing:
            raise GitHubAgentError(
                f"required checks not satisfied; missing={missing}, failing={failing}"
            )
        return {
            "repository": repository,
            "ref": ref,
            "required": json_array(required, context="GitHub required checks"),
            "status": "ok",
        }

    def merge_pull_request(
        self,
        repository: str,
        number: int,
        delete_source_branch_after_merge: bool,
        merge_method: str = "squash",
        commit_title: str | None = None,
        commit_message: str | None = None,
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        if type(delete_source_branch_after_merge) is not bool:
            raise GitHubAgentError("Explicit keep/delete source branch choice required")
        if not expected_head_sha:
            raise GitHubAgentError("expected_head_sha is required for merge")
        repository = self._assert_allowed(repository)
        if merge_method not in {"merge", "squash", "rebase"}:
            raise GitHubAgentError("merge_method must be merge, squash, or rebase")
        _, pull = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
        )
        if not isinstance(pull, dict):
            raise GitHubAgentError("unexpected pull request response")
        head = json_member_object(pull, "head")
        base = json_member_object(pull, "base")
        head_repo = json_member_object(head, "repo")
        base_repo = json_member_object(base, "repo")
        if json_str(head_repo.get("full_name")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request merge is disabled")
        if json_str(base_repo.get("full_name")).casefold() != repository.casefold():
            raise GitHubAgentError("cross-repository pull request merge is disabled")
        head_sha = json_str(head.get("sha"))
        if not head_sha:
            raise GitHubAgentError("pull request head has no sha")
        if expected_head_sha and head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"pull request head changed: expected {expected_head_sha}, found {head_sha}"
            )
        source_branch = json_str(head.get("ref"))
        target_branch = json_str(base.get("ref"))
        if delete_source_branch_after_merge:
            self._assert_mutable_branch(source_branch)
            if not source_branch or source_branch == target_branch:
                raise GitHubAgentError("Cannot delete merge target branch")
        _, repo = self._repo_request(repository, "GET", f"/repos/{repository}")
        if not isinstance(repo, dict):
            raise GitHubAgentError("Current repository settings required")
        if not delete_source_branch_after_merge and repo.get("delete_branch_on_merge"):
            raise GitHubAgentError("Repository auto-delete conflicts with explicit keep choice; disable it first")
        if delete_source_branch_after_merge and source_branch == repo.get("default_branch"):
            raise GitHubAgentError("Cannot delete default branch")
        if delete_source_branch_after_merge:
            _, source = self._repo_request(repository, "GET", f"/repos/{repository}/branches/{self._quote(source_branch)}")
            if not isinstance(source, dict) or source.get("protected"):
                raise GitHubAgentError("Cannot delete protected branch")
        self.assert_required_checks(repository, head_sha)

        # The merge argument is an explicit confirmation/change of the stored
        # choice. Persist it before merging so retries and other reviewers see it.
        if branch_choice(json_str(pull.get("body"))) is not delete_source_branch_after_merge:
            self._repo_request(repository, "PATCH", f"/repos/{repository}/pulls/{number}",
                payload={"body": with_branch_choice(json_str(pull.get("body")), delete_source_branch_after_merge)})

        payload: JsonObject = {"merge_method": merge_method, "sha": head_sha}
        if commit_title:
            payload["commit_title"] = commit_title
        if commit_message:
            payload["commit_message"] = commit_message
        _, result = self._repo_request(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{number}/merge",
            payload=payload,
        )
        if not isinstance(result, dict):
            raise GitHubAgentError("unexpected pull request merge response")
        source_state = "kept"
        cleanup = None
        if result.get("merged") and delete_source_branch_after_merge:
            source_state = "not_deleted"
            try:
                status, current = self._repo_request(repository, "GET",
                    f"/repos/{repository}/git/ref/heads/{self._quote(source_branch)}", allowed_errors={404})
                if status == 404:
                    source_state = "deleted"
                elif isinstance(current, dict) and json_member_object(current, "object").get("sha") == head_sha:
                    # REST DELETE has no expected-SHA precondition. Git transport
                    # force-with-lease makes deletion compare-and-swap on the server.
                    deleter = getattr(self, "_delete_source_branch_cas", None)
                    if deleter is None:
                        source_state = "cleanup_not_supported"
                    else:
                        deleter(repository, source_branch, head_sha)
                        source_state = "deleted"
                else:
                    source_state = "preserved_head_changed"
            except (GitHubAgentError, ValueError):
                # Merge is already committed. Report cleanup separately; never imply a retry is safe.
                source_state = "cleanup_failed"
        if result.get("merged") and source_state == "deleted":
            cleaner = getattr(self, "_cleanup_merged_worktrees", None)
            if cleaner is not None:
                try:
                    cleanup = cleaner(repository, source_branch, head_sha)
                except Exception:
                    cleanup = {"status": "cleanup_failed", "preserved": True}
        return {
            "repository": repository,
            "number": number,
            "merged": bool(result.get("merged", False)),
            "sha": json_str(result.get("sha")),
            "message": json_str(result.get("message")),
            "merge_method": merge_method,
            "delete_source_branch_after_merge": delete_source_branch_after_merge,
            "source_branch": source_branch,
            "source_branch_state": source_state if result.get("merged") else "merge_not_completed",
            "local_cleanup": cleanup,
        }
