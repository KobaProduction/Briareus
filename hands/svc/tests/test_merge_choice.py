"""Explicit source-branch intent survives PR creation, edits and MCP validation."""

import unittest
from unittest.mock import patch

from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError
from pydantic import BaseModel

from common.merge_policy import branch_choice, with_branch_choice
from modules.github.pulls import GitHubPullClient
from modules.gitlab.merge_requests import GitLabMergeRequestClient
from modules.gitlab.models import GitLabProfile
from service_runtime.http_transport import HttpTransportResponse
from source_control.providers.github.infrastructure.schemas.collaboration import (
    PullCreate,
    PullRef,
    PullRequestRecord,
    PullUpdate,
)
from source_control.providers.gitlab.infrastructure.schemas.merge_requests import (
    MergeRequest,
    MergeRequestCreate,
)


def github_pull(body: str) -> PullRequestRecord:
    return PullRequestRecord(
        number=1,
        title="Title",
        state="open",
        body=body,
        html_url="https://github.test/pull/1",
        node_id="fixture",
        head=PullRef(ref="feature", sha="a" * 40),
        base=PullRef(ref="main", sha="b" * 40),
    )


def gitlab_client() -> GitLabMergeRequestClient:
    return GitLabMergeRequestClient(
        GitLabProfile(
            account_id="fixture",
            alias="fixture",
            base_url="https://gitlab.test",
            auth_type="private_token",
        )
    )


def wire_response(status: int, value: BaseModel) -> HttpTransportResponse:
    return HttpTransportResponse(
        status=status, headers={}, body=value.model_dump_json().encode(), will_close=False
    )


class MergeChoiceTests(unittest.TestCase):
    def test_marker_replaces_old_choice_without_changing_description(self) -> None:
        self.assertIs(branch_choice(with_branch_choice("Description", False)), False)
        self.assertIs(
            branch_choice(with_branch_choice(with_branch_choice("Description", False), True)), True
        )

    def test_github_create_persists_choice_and_read_exposes_it(self) -> None:
        client = GitHubPullClient()

        def request(
            repository: str,
            method: str,
            path: str,
            *,
            payload: BaseModel | None = None,
            allowed_errors: set[int] | None = None,
        ) -> HttpTransportResponse:
            del allowed_errors
            self.assertEqual(
                (repository, method, path), ("owner/repo", "POST", "/repos/owner/repo/pulls")
            )
            assert isinstance(payload, PullCreate)
            self.assertIs(branch_choice(payload.body), True)
            self.assertTrue(payload.body.startswith("Description"))
            return wire_response(201, github_pull(payload.body))

        with patch.object(client, "_repo_transport", side_effect=request):
            result = client.create_pull_request(
                "owner/repo", "Title", "feature", "main", True, "Description"
            )
        self.assertIs(result.pull_request.delete_source_branch_after_merge, True)

    def test_github_description_edit_preserves_provider_choice(self) -> None:
        client = GitHubPullClient()
        current = github_pull(with_branch_choice("old", False))
        edited = github_pull(with_branch_choice("New description", False))
        with patch.object(
            client,
            "_repo_transport",
            side_effect=[wire_response(200, current), wire_response(200, edited)],
        ) as request:
            result = client.update_pull_request("owner/repo", 1, body="New description")
        payload = request.call_args.kwargs["payload"]
        assert isinstance(payload, PullUpdate) and payload.body is not None
        self.assertIs(branch_choice(payload.body), False)
        self.assertTrue(payload.body.startswith("New description"))
        self.assertIs(result.pull_request.delete_source_branch_after_merge, False)

    def test_gitlab_create_uses_same_required_choice_and_native_storage(self) -> None:
        client = gitlab_client()
        created = MergeRequest(
            id=1,
            iid=1,
            project_id=1,
            title="Title",
            state="opened",
            created_at="",
            updated_at="",
            web_url="https://gitlab.test/merge_requests/1",
            source_branch="feature",
            target_branch="main",
            source_project_id=1,
            target_project_id=1,
            sha="a" * 40,
        )
        with patch.object(
            client, "_request_transport", return_value=wire_response(201, created)
        ) as request:
            result = client.create_merge_request("owner/repo", "feature", "main", "Title", False)
        payload = request.call_args.kwargs["payload"]
        assert isinstance(payload, MergeRequestCreate)
        self.assertIs(payload.remove_source_branch, False)
        self.assertEqual(result.merge_request.iid, 1)


class MergeChoiceMcpTests(unittest.IsolatedAsyncioTestCase):
    async def test_null_branch_choice_is_rejected_before_provider_io(self) -> None:
        github = GitHubPullClient()
        gitlab = gitlab_client()
        server = FastMCP("merge-choice-fixture")
        server.tool(name="github_create")(github.create_pull_request)
        server.tool(name="gitlab_create")(gitlab.create_merge_request)
        server.tool(name="branch_choice")(with_branch_choice)
        with (
            patch.object(github, "_repo_transport") as github_request,
            patch.object(gitlab, "_request_transport") as gitlab_request,
        ):
            async with Client(server) as client:
                with self.assertRaises(ToolError):
                    await client.call_tool(
                        "github_create",
                        {
                            "repository": "owner/repo",
                            "title": "Title",
                            "head": "feature",
                            "base": "main",
                            "delete_source_branch_after_merge": None,
                        },
                    )
                with self.assertRaises(ToolError):
                    await client.call_tool(
                        "gitlab_create",
                        {
                            "project": "owner/repo",
                            "title": "Title",
                            "source_branch": "feature",
                            "target_branch": "main",
                            "delete_source_branch_after_merge": None,
                        },
                    )
                with self.assertRaises(ToolError):
                    await client.call_tool(
                        "branch_choice", {"body": "body", "delete_source_branch_after_merge": None}
                    )
        github_request.assert_not_called()
        gitlab_request.assert_not_called()
