"""Provider codecs and MCP receipts preserve the original graph tool wire."""

import json
import unittest
from unittest.mock import patch

from fastmcp import Client, FastMCP
from mcp.types import TextContent, ToolAnnotations
from test_history_rewrite import HistoryFixture

from modules.github.application.history import RewriteCommand, RewriteHistory, RewriteTarget
from modules.github.domain.history import GitCommit, GitIdentity, GitSignature
from modules.github.github_actions import GitHubActionsClient
from modules.github.github_actions_tools import register_github_actions_tools
from modules.github.github_agent import GitHubAgentError
from modules.github.history_result import history_result
from modules.github.infrastructure.history import GitHubHistory
from service_runtime.http_transport import HttpTransportResponse
from source_control.providers.github.infrastructure.schemas.repository import (
    GitCommitCreate,
    GitReferenceUpdate,
    GitSignatureRequest,
)


class HistoryProtocolTests(unittest.TestCase):
    def test_create_serializes_exact_identity_and_optional_original_dates(self) -> None:
        client = GitHubActionsClient()
        original = GitCommit(
            "old",
            "tree",
            "message",
            ("parent",),
            GitSignature("Old", "old@example.test", "author-date"),
            GitSignature("Old", "old@example.test", "committer-date"),
        )
        raw = {
            "sha": "new",
            "tree": {"sha": "tree"},
            "message": "message",
            "parents": [{"sha": "new-parent"}],
            "author": {"name": "Agent", "email": "agent@example.test"},
            "committer": {"name": "Agent", "email": "agent@example.test"},
        }
        with patch.object(
            client,
            "_repo_transport",
            return_value=HttpTransportResponse(
                status=201,
                headers={},
                body=json.dumps(raw).encode(),
                will_close=False,
            ),
        ) as request:
            receipt = GitHubHistory(client).create(
                RewriteTarget("owner/repo", "feature/name"),
                original,
                ("new-parent",),
                GitIdentity("Agent", "agent@example.test"),
                preserve_dates=True,
            )
        self.assertEqual(receipt.sha, "new")
        self.assertEqual(receipt.parents, ("new-parent",))
        self.assertEqual(
            request.call_args.args, ("owner/repo", "POST", "/repos/owner/repo/git/commits")
        )
        self.assertEqual(
            request.call_args.kwargs["payload"],
            GitCommitCreate(
                message="message",
                tree="tree",
                parents=["new-parent"],
                author=GitSignatureRequest(
                    name="Agent", email="agent@example.test", date="author-date"
                ),
                committer=GitSignatureRequest(
                    name="Agent", email="agent@example.test", date="committer-date"
                ),
            ),
        )

    def test_malformed_provider_commit_is_rejected(self) -> None:
        client = GitHubActionsClient()
        target = RewriteTarget("owner/repo", "feature/name")
        for raw in (
            b'{"sha":"new","message":"fixture","tree":{"sha":""}}',
            b'{"sha":"new","message":"fixture","tree":{"sha":"tree"},"parents":[{"sha":""}]}',
        ):
            with (
                self.subTest(raw=raw),
                patch.object(
                    client,
                    "_repo_transport",
                    return_value=HttpTransportResponse(
                        status=200,
                        headers={},
                        body=raw,
                        will_close=False,
                    ),
                ),
                self.assertRaises(GitHubAgentError),
            ):
                GitHubHistory(client).commit(target, "new")

    def test_branch_reads_and_force_update_use_existing_encoded_paths(self) -> None:
        client = GitHubActionsClient()
        target = RewriteTarget("owner/repo", "feature/name")
        with patch.object(
            client,
            "_repo_transport",
            return_value=HttpTransportResponse(
                status=200,
                headers={},
                body=b'{"object":{"sha":"old"}}',
                will_close=False,
            ),
        ) as request:
            self.assertEqual(GitHubHistory(client).head(target, confirming=True), "old")
            self.assertEqual(
                request.call_args.args[2], "/repos/owner/repo/git/ref/heads/feature%2Fname"
            )
            GitHubHistory(client).replace_head(target, "new")
            self.assertEqual(
                request.call_args.args[2], "/repos/owner/repo/git/refs/heads/feature%2Fname"
            )
            self.assertEqual(
                request.call_args.kwargs["payload"], GitReferenceUpdate(sha="new", force=True)
            )

    def test_mcp_receipt_preserves_mapping_and_plan_and_sdk_aliases(self) -> None:
        result = RewriteHistory(HistoryFixture()).execute(RewriteCommand("repo", "branch", "merge"))
        receipt = history_result(result)
        payload = receipt.structured_content
        if payload is None:
            self.fail("structured MCP receipt required")
        self.assertEqual(
            payload["mapping"],
            {"root": "new-root", "left": "new-left", "right": "new-right", "merge": "new-merge"},
        )
        self.assertEqual(payload["commit_count"], 4)
        self.assertEqual(payload["merge_commit_count"], 1)
        self.assertEqual(payload["rewritten_commit_count"], 4)
        self.assertFalse(payload["ref_updated"])
        self.assertTrue(payload["dry_run_creates_unreferenced_commit_objects"])
        wire = receipt.model_dump(mode="json", by_alias=True)
        self.assertEqual(wire["structuredContent"], payload)
        self.assertFalse(wire["isError"])
        text = receipt.content[0]
        if not isinstance(text, TextContent):
            self.fail("text MCP receipt required")
        self.assertEqual(json.loads(text.text), payload)


class HistoryMcpDispatchTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_tool_emits_existing_structured_receipt_without_model_wrapper(
        self,
    ) -> None:
        server = FastMCP("history-rewrite-fixture")
        provider = GitHubActionsClient()
        annotations = ToolAnnotations()
        register_github_actions_tools(
            server, lambda _account: provider, annotations, annotations, annotations
        )
        result = RewriteHistory(HistoryFixture()).execute(RewriteCommand("repo", "branch", "merge"))
        with patch(
            "source_control.providers.github.github_actions_tools.rewrite_branch_identity_graph",
            return_value=result,
        ):
            async with Client(server) as client:
                receipt = await client.call_tool(
                    "github_agent_rewrite_branch_identity_graph",
                    {
                        "account_id": "fixture-account",
                        "repository": "repo",
                        "branch": "branch",
                        "expected_head_sha": "merge",
                    },
                )
        self.assertFalse(receipt.is_error)
        payload = receipt.structured_content
        if payload is None:
            self.fail("structured receipt required through real MCP dispatch")
        self.assertEqual(payload["old_head_sha"], "merge")
        self.assertEqual(payload["new_head_sha"], "new-merge")
        self.assertEqual(payload["commit_count"], 4)
        self.assertNotIn("result", payload)
