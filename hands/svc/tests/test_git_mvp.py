"""MVP Git merge, public read, pagination and real local-worktree acceptance."""

import inspect
import tempfile
import unittest
from contextlib import nullcontext
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

from pydantic import BaseModel
from test_account_lease import account
from test_merge_choice import gitlab_client

from modules.github.github_agent import GitHubAgentError, GitHubAppClient
from modules.github.issues import GitHubIssueClient
from modules.github.pulls import GitHubPullClient
from modules.gitlab.errors import GitLabError
from modules.gitlab.infrastructure.schemas.merge_requests import MergeRequestAccept
from service_runtime.http_transport import HttpTransportResponse
from service_runtime.repository_checkout import RepositoryCheckoutError
from source_control.providers.github.application.review_gates import RequiredChecksReceipt
from source_control.providers.github.infrastructure.schemas.collaboration import (
    PullMergeRequest,
    PullRef,
    PullRequestRecord,
    RepositoryReference,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequest,
)
from svc_hand.infrastructure.checkout import canonical_repository
from svc_hand.infrastructure.git_process import GitEnvironment, GitProcess, git_environment, run_git
from svc_hand.node_git import NodeGitHubClient, _checkout, _cleanup_merged


@dataclass(frozen=True)
class GitCall:
    method: str
    path: str
    payload: BaseModel | None = None
    expected_head: str | None = None


def reply(status: int, body: bytes) -> HttpTransportResponse:
    return HttpTransportResponse(status=status, headers={}, body=body, will_close=False)


class ReadmeContent(BaseModel):
    content: str


class MergeFixture(GitHubPullClient):
    def __init__(self) -> None:
        super().__init__(protected_branches=frozenset(), required_checks=())
        self.calls: list[GitCall] = []
        self.expected = "a" * 40
        self.auto_delete = False
        self.protected = False
        self.changed = False
        self.merged = True

    def assert_required_checks(self, repository: str, ref: str) -> RequiredChecksReceipt:
        return RequiredChecksReceipt(repository, ref, (), "ok")

    def _delete_source_branch_cas(self, repository: str, branch: str, expected_head: str) -> None:
        self.assert_repository(repository)
        self.calls.append(GitCall("CAS_DELETE", branch, expected_head=expected_head))

    @staticmethod
    def assert_repository(repository: str) -> None:
        if repository != "owner/repo":
            raise AssertionError("Unexpected fixture repository")

    def _repo_transport(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None = None,
        allowed_errors: set[int] | None = None,
    ) -> HttpTransportResponse:
        del allowed_errors
        self.assert_repository(repository)
        self.calls.append(GitCall(method, path, payload))
        if path.endswith("/pulls/1"):
            pull = PullRequestRecord(
                number=1,
                title="Fixture",
                state="open",
                html_url="",
                node_id="fixture",
                head=PullRef(
                    ref="feature", sha=self.expected, repo=RepositoryReference(full_name=repository)
                ),
                base=PullRef(
                    ref="main", sha="b" * 40, repo=RepositoryReference(full_name=repository)
                ),
            )
            return reply(200, pull.model_dump_json().encode())
        if path.endswith("/pulls/1/merge"):
            merged = b"true" if self.merged else b"false"
            return reply(200, b'{"merged":' + merged + b',"sha":"' + b"b" * 40 + b'"}')
        if "/branches/" in path:
            return reply(200, b'{"protected":true}' if self.protected else b'{"protected":false}')
        if "/git/ref/heads/" in path:
            head = "c" * 40 if self.changed else self.expected
            return reply(200, ('{"object":{"sha":"' + head + '"}}').encode())
        if method == "DELETE":
            return reply(204, b"{}")
        deletion = b"true" if self.auto_delete else b"false"
        return reply(200, b'{"default_branch":"main","delete_branch_on_merge":' + deletion + b"}")


def fixture_git(target: Path, *arguments: str) -> str:
    """Only disposable fixture repositories admit local file transport."""
    variables = tuple(
        (name, "file:https" if name == "GIT_ALLOW_PROTOCOL" else value)
        for name, value in git_environment("", "").variables
    )
    process = GitProcess(target, arguments, GitEnvironment(variables))
    try:
        return process.capture(None)
    finally:
        process.close()


def git(*arguments: str | Path) -> str:
    return fixture_git(Path(tempfile.gettempdir()), *(str(argument) for argument in arguments))


def node_client(root: Path) -> NodeGitHubClient:
    current = account()
    assert current.credential is not None
    return NodeGitHubClient(
        token=current.credential, account_id=str(current.id), workspace_root=root
    )


class GitMvpTests(unittest.TestCase):
    def test_merge_requires_choice_and_sha_and_pins_actual_merge(self) -> None:
        client = MergeFixture()
        with self.assertRaises(TypeError):
            inspect.signature(client.merge_pull_request).bind("owner/repo", 1)
        with self.assertRaises(GitHubAgentError):
            client.merge_pull_request("owner/repo", 1, False)
        result = client.merge_pull_request(
            "owner/repo", 1, False, expected_head_sha=client.expected
        )
        merge = next(call for call in client.calls if call.method == "PUT")
        assert isinstance(merge.payload, PullMergeRequest)
        self.assertEqual(merge.payload.sha, client.expected)
        self.assertEqual(result.source_branch_state, "kept")
        self.assertFalse(any(call.method == "CAS_DELETE" for call in client.calls))

    def test_keep_conflict_and_delete_protection(self) -> None:
        client = MergeFixture()
        client.auto_delete = True
        with self.assertRaises(GitHubAgentError):
            client.merge_pull_request("owner/repo", 1, False, expected_head_sha=client.expected)
        self.assertFalse(any(call.method == "PUT" for call in client.calls))
        client = MergeFixture()
        client.protected = True
        with self.assertRaises(GitHubAgentError):
            client.merge_pull_request("owner/repo", 1, True, expected_head_sha=client.expected)
        self.assertFalse(any(call.method == "PUT" for call in client.calls))

    def test_delete_only_after_confirmed_merge_and_unchanged_branch(self) -> None:
        client = MergeFixture()
        result = client.merge_pull_request("owner/repo", 1, True, expected_head_sha=client.expected)
        self.assertEqual(result.source_branch_state, "deleted")
        self.assertLess(
            next(i for i, call in enumerate(client.calls) if call.method == "PUT"),
            next(i for i, call in enumerate(client.calls) if call.method == "CAS_DELETE"),
        )
        client = MergeFixture()
        client.changed = True
        result = client.merge_pull_request("owner/repo", 1, True, expected_head_sha=client.expected)
        self.assertEqual(result.source_branch_state, "preserved_head_changed")
        self.assertFalse(any(call.method == "CAS_DELETE" for call in client.calls))
        client = MergeFixture()
        client.merged = False
        client.merge_pull_request("owner/repo", 1, True, expected_head_sha=client.expected)
        self.assertFalse(any(call.method == "CAS_DELETE" for call in client.calls))

    def test_public_read_uses_selected_app_without_alias_and_never_writes(self) -> None:
        client = GitHubAppClient()
        with (
            patch.object(
                client,
                "_installation_token",
                side_effect=GitHubAgentError("is not installed for GitHub App"),
            ),
            patch.object(
                client,
                "_request_transport",
                side_effect=[reply(200, b'{"private":false}'), reply(200, b'{"content":"public"}')],
            ) as request,
        ):
            result = client._repo_model(
                "owner/public", "GET", "/repos/owner/public/readme", response_type=ReadmeContent
            )
            self.assertEqual(result.data.content, "public")
            self.assertTrue(all("token" not in call.kwargs for call in request.call_args_list))
        with (
            patch.object(
                client,
                "_installation_token",
                side_effect=GitHubAgentError("is not installed for GitHub App"),
            ),
            patch.object(client, "_request_transport") as request,
        ):
            with self.assertRaises(GitHubAgentError):
                client._repo_ack("owner/public", "PUT", "/repos/owner/public/contents/a")
            request.assert_not_called()

    def test_issue_next_page_survives_page_full_of_prs(self) -> None:
        client = GitHubIssueClient()
        response = HttpTransportResponse(
            status=200,
            headers={
                "link": '<https://api.github.com/repos/o/r/issues?page=3&per_page=100>; rel="next"'
            },
            body=b'[{"pull_request":{},"number":1,"title":"PR","state":"open","html_url":""}]',
            will_close=False,
        )
        with patch.object(client, "_repo_transport", return_value=response):
            result = client.list_issues("o/r", page=2, per_page=200)
        self.assertEqual(result.issues, [])
        self.assertTrue(result.has_next)
        self.assertEqual(result.next_page, 3)
        self.assertEqual(result.per_page, 100)
        self.assertEqual(result.raw_count, 1)

    def test_gitlab_merge_requires_choice_sha_and_preserves_provider_cas(self) -> None:
        client = gitlab_client()
        head = "a" * 40
        current = MergeRequest(
            id=1,
            iid=1,
            project_id=1,
            title="Fixture",
            state="opened",
            created_at="",
            updated_at="",
            web_url="",
            source_branch="feature",
            target_branch="main",
            source_project_id=1,
            target_project_id=1,
            sha=head,
        )
        merged = current.model_copy(update={"state": "merged"})
        with patch.object(
            client,
            "_request_transport",
            side_effect=[
                reply(200, current.model_dump_json().encode()),
                reply(200, merged.model_dump_json().encode()),
            ],
        ) as request:
            result = client.merge_merge_request("owner/repo", 1, False, sha=head)
        payload = request.call_args.kwargs["payload"]
        assert isinstance(payload, MergeRequestAccept)
        self.assertEqual(payload.sha, head)
        self.assertIs(payload.should_remove_source_branch, False)
        self.assertEqual(result.source_branch_action, "keep")
        with self.assertRaises(GitLabError):
            client.merge_merge_request("owner/repo", 1, True)
        changed = current.model_copy(update={"sha": "b" * 40})
        with patch.object(
            client,
            "_request_transport",
            return_value=reply(200, changed.model_dump_json().encode()),
        ) as request:
            with self.assertRaises(GitLabError):
                client.merge_merge_request("owner/repo", 1, True, sha=head)
            self.assertEqual(request.call_count, 1)

    def test_cas_delete_refuses_branch_updated_after_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / "seed"
            seed.mkdir()
            git("init", "--template=", seed)
            git("-C", seed, "config", "user.name", "Fixture")
            git("-C", seed, "config", "user.email", "fixture@example.invalid")
            (seed / "a").write_text("one")
            git("-C", seed, "add", ".")
            git("-C", seed, "commit", "-m", "one")
            old = git("-C", seed, "rev-parse", "HEAD")
            git("-C", seed, "branch", "feature")
            remote = root / "remote.git"
            git("clone", "--bare", "--template=", seed, remote)
            client = node_client(root)
            (seed / "a").write_text("two")
            git("-C", seed, "commit", "-am", "two")
            new = git("-C", seed, "rev-parse", "HEAD")
            git("-C", remote, "update-ref", "refs/heads/feature", old)
            git("-C", seed, "push", remote, "HEAD:refs/heads/feature")

            def local_transport(
                target: Path, *args: str, auth_scope: str = "", auth_header: str = ""
            ) -> str:
                if args[0] != "push":
                    return run_git(target, *args, auth_scope=auth_scope, auth_header=auth_header)
                rewritten = tuple(
                    str(remote) if item.startswith("https://github.com/") else item for item in args
                )
                return fixture_git(target, *rewritten)

            with patch("svc_hand.node_git._git", side_effect=local_transport):
                with self.assertRaises(ValueError):
                    client._delete_source_branch_cas("owner/repo", "feature", old)
                self.assertEqual(git("-C", remote, "rev-parse", "refs/heads/feature"), new)
                client._delete_source_branch_cas("owner/repo", "feature", new)
            with self.assertRaises(ValueError):
                git("-C", remote, "rev-parse", "--verify", "refs/heads/feature")
            self.assertEqual(list((root / ".briareus-git" / "repositories").glob(".delete-*")), [])

    def test_real_canonical_worktrees_reuse_and_preserve_dirty(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            seed = root / "seed"
            seed.mkdir()
            git("init", "--template=", seed)
            git("-C", seed, "config", "user.name", "Fixture")
            git("-C", seed, "config", "user.email", "fixture@example.invalid")
            (seed / "a.txt").write_text("initial")
            git("-C", seed, "add", ".")
            git("-C", seed, "commit", "-m", "fixture")
            client = node_client(root)
            url = client._expected_remote("owner/repo")
            canonical = canonical_repository(root, url)
            git("clone", "--bare", "--template=", seed, canonical)
            git("-C", canonical, "remote", "set-url", "origin", url)

            def offline(
                target: Path, *args: str, auth_scope: str = "", auth_header: str = ""
            ) -> str:
                if args[0] == "fetch":
                    return fixture_git(
                        target,
                        "fetch",
                        "--no-tags",
                        str(seed),
                        "+refs/heads/*:refs/remotes/origin/*",
                    )
                if args[0] == "ls-remote":
                    return fixture_git(target, "ls-remote", "--symref", str(seed), "HEAD")
                return run_git(target, *args, auth_scope=auth_scope, auth_header=auth_header)

            with patch("svc_hand.infrastructure.checkout.run_git", side_effect=offline):
                one = _checkout(client, "agents/a", url, "", "", mode="git", branch="agent/a")
                two = _checkout(client, "agents/b", url, "", "", mode="git", branch="agent/b")
                reused = _checkout(client, "agents/a", url, "", "", mode="git")
                self.assertEqual(one.canonical_repository, two.canonical_repository)
                self.assertTrue(reused.reused)
                self.assertNotEqual(one.branch, two.branch)
                with self.assertRaises(ValueError):
                    _checkout(client, "agents/a", url, "", "", mode="snapshot", overwrite=True)
                head = git("-C", root / "agents/a", "rev-parse", "HEAD")
                (root / "agents/a" / "a.txt").write_text("dirty work")
                kept = _cleanup_merged(client, "owner/repo", "agent/a", head)
                self.assertEqual(kept.preserved_worktrees, ("agents/a",))
                self.assertTrue((root / "agents/a").exists())
                removed = _cleanup_merged(client, "owner/repo", "agent/b", head)
                self.assertEqual(removed.removed_worktrees, ("agents/b",))
                self.assertFalse((root / "agents/b").exists())
                self.assertEqual((root / "agents/a" / "a.txt").read_text(), "dirty work")
                self.assertTrue(canonical.exists())
                with self.assertRaises(RepositoryCheckoutError):
                    _checkout(client, "../other-project", url, "", "", mode="git")


class DefaultRefFreshnessTests(unittest.TestCase):
    def test_checkout_selects_updated_remote_default_not_bare_head(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            canonical = root / "canonical.git"
            canonical.mkdir()
            calls: list[tuple[str, ...]] = []

            def remote_git(
                target: Path, *args: str, auth_scope: str = "", auth_header: str = ""
            ) -> str:
                del target, auth_scope, auth_header
                calls.append(args)
                if args[:3] == ("remote", "get-url", "origin"):
                    return "https://github.com/o/r.git"
                if args[:3] == ("ls-remote", "--symref", "origin"):
                    return "ref: refs/heads/main\tHEAD\nabc\tHEAD"
                return ""

            client = NodeGitHubClient(workspace_root=root)
            with (
                patch(
                    "svc_hand.infrastructure.checkout.canonical_repository", return_value=canonical
                ),
                patch(
                    "svc_hand.infrastructure._repository_lock_binding._RepositoryLockBinding.lock",
                    return_value=nullcontext(),
                ),
                patch("svc_hand.infrastructure.checkout.run_git", side_effect=remote_git),
            ):
                _checkout(
                    client,
                    "agent",
                    "https://github.com/o/r.git",
                    "",
                    "",
                    mode="git",
                    branch="feature",
                )
            add = next(args for args in calls if args[:2] == ("worktree", "add"))
            self.assertEqual(add[-1], "refs/remotes/origin/main")
