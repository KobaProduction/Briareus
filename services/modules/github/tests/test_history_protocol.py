"""Provider codecs and MCP receipts preserve the original graph tool wire."""

import json
import unittest
from unittest.mock import patch

from fastmcp import Client, FastMCP
from mcp.types import TextContent, ToolAnnotations
from pydantic import ValidationError

from modules.github.application.history import RewriteCommand, RewriteHistory, RewriteTarget
from modules.github.domain.history import GitCommit, GitIdentity, GitSignature
from modules.github.github_actions import GitHubActionsClient
from modules.github.github_actions_tools import register_github_actions_tools
from modules.github.history_result import history_result
from modules.github.infrastructure.history import GitHubHistory
from modules.github.tests.test_history_rewrite import HistoryFixture
from source_control.providers.github.infrastructure.schemas.repository import (
    GitCommitRecord,
    GitReferenceRecord,
)
from source_control.providers.github.transport_views import (
    GitHubAcknowledgement,
    GitHubModelResponse,
    GitHubPagination,
)


class HistoryProtocolTests(unittest.TestCase):
    def test_create_serializes_exact_identity_and_optional_original_dates(self) -> None:
        client = object.__new__(GitHubActionsClient)
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
            "_repo_model",
            return_value=GitHubModelResponse(
                201, GitCommitRecord.model_validate(raw), GitHubPagination()
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
            request.call_args.kwargs["payload"].model_dump(mode="json", exclude_none=True),
            {
                "message": "message",
                "tree": "tree",
                "parents": ["new-parent"],
                "author": {"name": "Agent", "email": "agent@example.test", "date": "author-date"},
                "committer": {
                    "name": "Agent",
                    "email": "agent@example.test",
                    "date": "committer-date",
                },
            },
        )

    def test_malformed_provider_commit_is_rejected(self) -> None:
        for raw, location in (
            ('{"sha":"new","message":"fixture","tree":{"sha":""}}', ("tree", "sha")),
            (
                '{"sha":"new","message":"fixture","tree":{"sha":"tree"},"parents":[{"sha":""}]}',
                ("parents", 0, "sha"),
            ),
        ):
            with self.subTest(raw=raw), self.assertRaises(ValidationError) as rejected:
                GitCommitRecord.model_validate_json(raw)
            self.assertEqual(rejected.exception.errors()[0]["loc"], location)

    def test_branch_reads_and_force_update_use_existing_encoded_paths(self) -> None:
        client = object.__new__(GitHubActionsClient)
        target = RewriteTarget("owner/repo", "feature/name")
        response = GitHubModelResponse(
            200,
            GitReferenceRecord.model_validate({"object": {"sha": "old"}}),
            GitHubPagination(),
        )
        with patch.object(client, "_repo_model", return_value=response) as read:
            self.assertEqual(GitHubHistory(client).head(target, confirming=True), "old")
            self.assertEqual(
                read.call_args.args[2], "/repos/owner/repo/git/ref/heads/feature%2Fname"
            )
            self.assertIs(read.call_args.kwargs["response_type"], GitReferenceRecord)
        with patch.object(client, "_repo_ack", return_value=GitHubAcknowledgement(200)) as write:
            GitHubHistory(client).replace_head(target, "new")
            self.assertEqual(
                write.call_args.args[2], "/repos/owner/repo/git/refs/heads/feature%2Fname"
            )
            self.assertEqual(
                write.call_args.kwargs["payload"].model_dump(mode="json"),
                {"sha": "new", "force": True},
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
        server: FastMCP[None] = FastMCP("history-rewrite-fixture")
        provider = object.__new__(GitHubActionsClient)
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
