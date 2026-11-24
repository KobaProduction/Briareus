from __future__ import annotations

import hashlib
import inspect
import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from briareus_git.provider_tools import register_account_tools
from briareus_github import github_actions_tools
from briareus_github.github_actions_tools import register_github_actions_tools
from briareus_github.github_collab_tools import register_github_collab_tools
from briareus_github.github_core_tools import register_github_core_tools
from briareus_github.github_identity import GitHubPrettyIdentityClient
from briareus_github.github_review_tools import register_github_review_tools
from briareus_github.github_tools import register_github_workflow_tools
from briareus_github.workflow_guard import SOURCE_MUTATION_TOOLS, GitHubLocalFirstMiddleware
from briareus_github_policy import GitHubRuntimePolicy
from briareus_gitlab.gitlab_client import GitLabClient
from briareus_gitlab.gitlab_tools import register_gitlab_tools
from briareus_gitlab.workflow_guard import (
    SOURCE_MUTATION_TOOLS as GITLAB_SOURCE_MUTATION_TOOLS,
)
from briareus_gitlab.workflow_guard import (
    GitLabLocalFirstMiddleware,
)
from briareus_gitlab_policy import GitLabRuntimePolicy
from briareus_tool_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, WRITE_EXTERNAL
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

CONTRACTS = Path(__file__).with_name("unified_tool_contracts.json")
GITLAB_CONTRACTS = Path(__file__).with_name("gitlab_tool_contracts.json")


def github_server(*, middleware: bool = False) -> tuple[FastMCP, MagicMock]:
    provider = MagicMock(spec=GitHubPrettyIdentityClient, unsafe=True)
    provider.list_repositories.return_value = {"items": []}
    provider.status.return_value = {"status": "ok"}
    provider.get_file.return_value = {"path": "README.md", "content": "test"}
    provider.create_repository.return_value = {"created": True, "private": True}
    provider.create_review_with_comments.return_value = {"review": "ok"}
    provider.merge_pull_request.return_value = {"merged": True}
    provider.create_pull_request.return_value = {"number": 4}
    provider.get_commit.return_value = {"sha": "123"}
    mcp = FastMCP("GitHub Unified Contract")

    def policy() -> GitHubRuntimePolicy:
        return GitHubRuntimePolicy()

    if middleware:
        mcp.middleware.insert(0, GitHubLocalFirstMiddleware(policy))

    def account_capabilities(_account: str, _repository: str) -> dict:
        return {}

    def client_factory(_account: str) -> MagicMock:
        return provider

    register_account_tools(
        mcp, lambda: {"accounts": []}, account_capabilities, READ_EXTERNAL, "GitHub"
    )
    register_github_core_tools(
        mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL, policy
    )
    register_github_workflow_tools(
        mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL
    )
    register_github_review_tools(mcp, client_factory, READ_EXTERNAL)
    register_github_collab_tools(mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL)
    register_github_actions_tools(
        mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL
    )
    return mcp, provider


def gitlab_server(*, middleware: bool = False) -> tuple[FastMCP, MagicMock]:
    provider = MagicMock(spec=GitLabClient, unsafe=True)
    provider.list_projects.return_value = {"projects": []}
    provider.create_project.return_value = {"created": True, "visibility": "private"}
    mcp = FastMCP("GitLab Unified Contract")
    if middleware:
        mcp.middleware.insert(0, GitLabLocalFirstMiddleware(GitLabRuntimePolicy))

    def account_capabilities(_account: str, _repository: str) -> dict:
        return {}

    def client_factory(_account: str) -> MagicMock:
        return provider

    context = SimpleNamespace(
        accounts=lambda: {"accounts": []},
        account_capabilities=account_capabilities,
        client=client_factory,
    )
    register_gitlab_tools(mcp, context, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL)
    return mcp, provider


def synthetic_required_value(name: str, schema: dict) -> object:
    """Generate protocol-valid minimal arguments for a mocked provider invocation."""
    specific: dict[str, object] = {
        "account_id": "agent",
        "repository": "owner/repo",
        "project": "group/repo",
        "owner": "owner",
        "name": "dram-repair",
        "destination": "projects/repo",
        "path": "README.md",
        "file_path": "README.md",
        "visibility": "private",
        "event": "COMMENT",
        "expected_head_sha": "a" * 40,
        "content_base64": "dGVzdA==",
    }
    if name in specific:
        return specific[name]
    if schema.get("enum"):
        return schema["enum"][0]
    datatype = schema.get("type")
    if datatype == "integer":
        return 1
    if datatype == "boolean":
        return True
    if datatype == "number":
        return 1.0
    if datatype == "array":
        return []
    if datatype == "object":
        return {}
    return "test"


def mock_all_provider_methods(provider: MagicMock, client_type: type) -> None:
    """Mock actual provider methods, including shared registrations; never call network."""
    for name, method in inspect.getmembers(client_type, inspect.isfunction):
        if not name.startswith("_") and callable(method):
            getattr(provider, name).return_value = {"ok": True, "method": name}


class UnifiedMcpSurfaceContracts(unittest.IsolatedAsyncioTestCase):
    async def test_every_github_command_preserves_schema_and_permissions(self) -> None:
        mcp, _ = github_server()
        tools = await mcp.list_tools()
        expected = json.loads(CONTRACTS.read_text(encoding="utf-8"))["schema_hashes"]
        names = [tool.name for tool in tools]
        self.assertEqual(len(names), len(set(names)), "duplicate GitHub tool names")
        self.assertEqual(set(names), set(expected), "missing or unexpected GitHub operations")
        for tool in tools:
            with self.subTest(tool=tool.name):
                self.assertFalse(tool.name.startswith(("github_", "agent_", "reviewer_")))
                contract = {
                    "inputSchema": tool.parameters,
                    "annotations": tool.annotations.model_dump(mode="json")
                    if tool.annotations
                    else None,
                }
                digest = hashlib.sha256(
                    json.dumps(
                        contract, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                    ).encode("utf-8")
                ).hexdigest()
                self.assertEqual(digest, expected[tool.name], "schema/permission regression")
        self.assertTrue(set(names) >= SOURCE_MUTATION_TOOLS)
        self.assertNotIn("create_repository", SOURCE_MUTATION_TOOLS)

    async def test_github_real_mcp_transport_and_account_selection(self) -> None:
        mcp, provider = github_server()
        async with Client(mcp) as client:
            response = await client.list_tools()
            self.assertEqual(len(response), 71)
            for name, args, method in (
                ("status", {"account_id": "reviewer", "repository": "owner/repo"}, "status"),
                (
                    "get_file",
                    {"account_id": "reviewer", "repository": "owner/repo", "path": "README.md"},
                    "get_file",
                ),
                (
                    "get_commit",
                    {"account_id": "reviewer", "repository": "owner/repo", "ref": "main"},
                    "get_commit",
                ),
                (
                    "create_repository",
                    {"account_id": "agent", "owner": "owner", "name": "dram-repair"},
                    "create_repository",
                ),
                (
                    "create_review",
                    {
                        "account_id": "reviewer",
                        "repository": "owner/repo",
                        "number": 1,
                        "event": "COMMENT",
                        "body": "test",
                    },
                    "create_review_with_comments",
                ),
                (
                    "merge_pull_request",
                    {"account_id": "agent", "repository": "owner/repo", "number": 1},
                    "merge_pull_request",
                ),
                (
                    "create_pull_request",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "title": "test",
                        "head": "feature",
                        "base": "main",
                    },
                    "create_pull_request",
                ),
            ):
                with self.subTest(tool=name):
                    await client.call_tool(name, args)
                    self.assertTrue(getattr(provider, method).called)
                    getattr(provider, method).reset_mock()

    async def test_consolidated_operations_preserve_all_variants(self) -> None:
        mcp, provider = github_server()
        mock_all_provider_methods(provider, GitHubPrettyIdentityClient)
        account = {"account_id": "reviewer", "repository": "owner/repo"}
        file_args = {**account, "path": "file.bin", "ref": "main"}
        write_args = {
            **account,
            "path": "file.bin",
            "branch": "main",
            "message": "write",
            "content": "/wA=",
        }
        pull_args = {**account, "number": 7, "expected_head_sha": "a" * 40}
        async with Client(mcp) as client:
            names = {tool.name for tool in await client.list_tools()}
            self.assertTrue(
                names.isdisjoint(
                    {
                        "add_pull_comment",
                        "capabilities",
                        "update_pull_branch_method",
                        "get_binary_file",
                        "put_binary_file",
                    }
                )
            )
            await client.call_tool("get_file", file_args)
            provider.get_file.assert_called_once_with("owner/repo", "file.bin", "main", "utf-8")
            provider.get_file.reset_mock()
            await client.call_tool("get_file", {**file_args, "encoding": "base64"})
            provider.get_file.assert_called_once_with("owner/repo", "file.bin", "main", "base64")
            await client.call_tool("put_file", write_args)
            provider.put_file.assert_called_once_with(
                "owner/repo", "file.bin", "/wA=", "write", "main", "utf-8"
            )
            provider.put_file.reset_mock()
            await client.call_tool("put_file", {**write_args, "encoding": "base64"})
            provider.put_file.assert_called_once_with(
                "owner/repo", "file.bin", "/wA=", "write", "main", "base64"
            )
            await client.call_tool("update_pull_branch", pull_args)
            provider.update_pull_branch.assert_called_once_with("owner/repo", 7, "a" * 40)
            for method in ("MERGE", "REBASE"):
                await client.call_tool("update_pull_branch", {**pull_args, "method": method})
                provider.update_pull_branch_graphql.assert_called_once_with(
                    "owner/repo", 7, method, "a" * 40
                )
                provider.update_pull_branch_graphql.reset_mock()
            for number in (1, 7):
                await client.call_tool(
                    "add_issue_comment", {**account, "number": number, "body": "conversation"}
                )
                provider.add_issue_comment.assert_called_once_with(
                    "owner/repo", number, "conversation"
                )
                provider.add_issue_comment.reset_mock()
            for name, args in (
                ("get_file", {**file_args, "encoding": "invalid"}),
                ("put_file", {**write_args, "encoding": "invalid"}),
                ("update_pull_branch", {**pull_args, "method": "SQUASH"}),
            ):
                with self.subTest(name=name), self.assertRaises(ToolError):
                    await client.call_tool(name, args)

    async def test_all_71_github_commands_dispatch_via_mcp(self) -> None:
        mcp, provider = github_server()
        mock_all_provider_methods(provider, GitHubPrettyIdentityClient)
        with (
            patch.object(
                github_actions_tools,
                "_rewrite_branch_identity_graph",
                return_value={"ok": True},
            ),
            patch.object(
                github_actions_tools,
                "_repoint_reserved_branch",
                return_value={"ok": True},
            ),
        ):
            async with Client(mcp) as client:
                tools = await mcp.list_tools()
                for tool in tools:
                    props = tool.parameters.get("properties", {})
                    args = {
                        key: synthetic_required_value(key, props.get(key, {}))
                        for key in tool.parameters.get("required", [])
                    }
                    with self.subTest(tool=tool.name):
                        result = await client.call_tool(tool.name, args)
                        self.assertFalse(result.is_error, f"{tool.name} failed")
        self.assertEqual(len(tools), 71)

    async def test_all_gitlab_commands_dispatch_via_mcp(self) -> None:
        mcp, provider = gitlab_server()
        # The GitLab code is owned by a separate Hand.
        mock_all_provider_methods(provider, GitLabClient)
        async with Client(mcp) as client:
            tools = await mcp.list_tools()
            for tool in tools:
                props = tool.parameters.get("properties", {})
                args = {
                    key: synthetic_required_value(key, props.get(key, {}))
                    for key in tool.parameters.get("required", [])
                }
                with self.subTest(tool=tool.name):
                    result = await client.call_tool(tool.name, args)
                    self.assertFalse(result.is_error, f"{tool.name} failed")
        self.assertEqual(len(tools), 61)

    async def test_source_mutation_protection_applies_to_all_renamed_tools(self) -> None:
        mcp, provider = github_server(middleware=True)
        async with Client(mcp) as client:
            for name, args in (
                (
                    "create_branch",
                    {"account_id": "agent", "repository": "owner/repo", "branch": "new"},
                ),
                (
                    "delete_file",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "path": "README.md",
                        "message": "delete",
                        "branch": "main",
                    },
                ),
                (
                    "merge_branch",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "base": "main",
                        "head": "feature",
                    },
                ),
                (
                    "rewrite_branch_identity",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "branch": "main",
                        "expected_head_sha": "a" * 40,
                    },
                ),
                (
                    "update_pull_branch",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "number": 2,
                        "method": "REBASE",
                    },
                ),
                (
                    "update_pull_branch",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "number": 2,
                        "method": "MERGE",
                    },
                ),
                (
                    "put_file",
                    {
                        "account_id": "agent",
                        "repository": "owner/repo",
                        "path": "image.bin",
                        "content": "/wA=",
                        "message": "binary",
                        "branch": "main",
                        "encoding": "base64",
                    },
                ),
            ):
                with self.subTest(tool=name), self.assertRaises(ToolError):
                    await client.call_tool(name, args)
            registered = {tool.name: tool for tool in await mcp.list_tools()}
            for name in sorted(SOURCE_MUTATION_TOOLS):
                tool = registered[name]
                props = tool.parameters.get("properties", {})
                required_args = {
                    key: synthetic_required_value(key, props.get(key, {}))
                    for key in tool.parameters.get("required", [])
                }
                with self.subTest(blocked_name=name), self.assertRaises(ToolError):
                    await client.call_tool(name, required_args)
            provider.create_branch.assert_not_called()
            provider.delete_file.assert_not_called()
            provider.merge_branch.assert_not_called()
            provider.rewrite_branch_identity.assert_not_called()
            provider.update_pull_branch_graphql.assert_not_called()
            provider.update_pull_branch.assert_not_called()
            provider.put_file.assert_not_called()
            # Creating a repository or PR is not a repository source-history mutation.
            await client.call_tool(
                "create_repository",
                {"account_id": "agent", "owner": "owner", "name": "dram-repair"},
            )
            provider.create_repository.assert_called_once()

    async def test_shared_provider_schema_and_gitlab_mutation_policy(self) -> None:
        github, _ = github_server()
        gitlab, provider = gitlab_server(middleware=True)
        gh = {tool.name: tool for tool in await github.list_tools()}
        gl = {tool.name: tool for tool in await gitlab.list_tools()}
        for name in (
            "accounts",
            "account_capabilities",
            "get_file",
            "get_commit",
            "create_branch",
            "delete_branch",
            "get_issue",
            "create_issue",
            "update_issue",
            "checkout_repository",
            "authorize_local_git",
            "list_tags",
            "create_tag",
            "delete_tag",
            "list_review_threads",
            "set_review_thread_resolved",
        ):
            self.assertEqual(gh[name].parameters, gl[name].parameters)
            self.assertEqual(gh[name].annotations, gl[name].annotations)
        for gh_name, gl_name in (
            ("workflow_job_log", "job_trace"),
            ("rerun_failed_workflow_jobs", "retry_pipeline"),
            ("cancel_workflow_run", "cancel_pipeline"),
        ):
            self.assertEqual(gh[gh_name].parameters, gl[gl_name].parameters)
            self.assertEqual(gh[gh_name].annotations, gl[gl_name].annotations)
        async with Client(gitlab) as client:
            for name in sorted(GITLAB_SOURCE_MUTATION_TOOLS):
                tool = gl[name]
                props = tool.parameters.get("properties", {})
                args = {
                    key: synthetic_required_value(key, props.get(key, {}))
                    for key in tool.parameters.get("required", [])
                }
                with self.subTest(tool=name), self.assertRaises(ToolError):
                    await client.call_tool(name, args)
            provider.create_tag.assert_not_called()
            provider.delete_tag.assert_not_called()
            provider.rebase_merge_request.assert_not_called()
            provider.put_file.assert_not_called()
            provider.create_pipeline.return_value = {"pipeline": {"id": 1}}
            await client.call_tool(
                "create_pipeline", {"account_id": "agent", "project": "group/repo", "ref": "main"}
            )
            provider.create_pipeline.assert_called_once()

    async def test_every_gitlab_command_preserves_schema_and_permissions(self) -> None:
        mcp, _ = gitlab_server()
        expected = json.loads(GITLAB_CONTRACTS.read_text(encoding="utf-8"))["schema_hashes"]
        tools = await mcp.list_tools()
        self.assertEqual({tool.name for tool in tools}, set(expected))
        for tool in tools:
            contract = {
                "inputSchema": tool.parameters,
                "annotations": tool.annotations.model_dump(mode="json")
                if tool.annotations
                else None,
            }
            digest = hashlib.sha256(
                json.dumps(
                    contract, sort_keys=True, ensure_ascii=True, separators=(",", ":")
                ).encode()
            ).hexdigest()
            with self.subTest(tool=tool.name):
                self.assertEqual(digest, expected[tool.name])

    async def test_gitlab_keeps_one_role_neutral_surface(self) -> None:
        mcp, provider = gitlab_server()
        tools = await mcp.list_tools()
        names = [tool.name for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        # The two workflow-reading tools are registered separately by the real runtime.
        self.assertEqual(len(names), 61)
        self.assertFalse(any(name.startswith(("agent_", "reviewer_", "gitlab_")) for name in names))
        self.assertIn("create_project", names)
        self.assertIn("add_note", names)
        self.assertNotIn("add_issue_note", names)
        self.assertNotIn("add_merge_request_note", names)
        async with Client(mcp) as client:
            await client.call_tool("create_project", {"account_id": "user", "name": "dram-repair"})
        provider.create_project.assert_called_once()
        self.assertEqual(provider.create_project.call_args.kwargs["visibility"], "private")


if __name__ == "__main__":
    unittest.main()
