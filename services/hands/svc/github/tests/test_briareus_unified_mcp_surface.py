from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from briareus_github import github_actions_tools
from briareus_github.account_tools import register_github_account_tools
from briareus_github.github_actions_tools import register_github_actions_tools
from briareus_github.github_collab_tools import register_github_collab_tools
from briareus_github.github_core_tools import register_github_core_tools
from briareus_github.github_review_tools import register_github_review_tools
from briareus_github.github_tools import register_github_workflow_tools
from briareus_github.workflow_guard import SOURCE_MUTATION_TOOLS, GitHubLocalFirstMiddleware
from briareus_github_policy import GitHubRuntimePolicy
from briareus_gitlab.gitlab_tools import register_gitlab_tools
from briareus_tool_annotations import DESTRUCTIVE_EXTERNAL, READ_EXTERNAL, WRITE_EXTERNAL
from fastmcp import Client, FastMCP
from fastmcp.exceptions import ToolError

CONTRACTS = Path(__file__).with_name("unified_tool_contracts.json")


def github_server(*, middleware: bool = False) -> tuple[FastMCP, MagicMock]:
    provider = MagicMock(unsafe=True)
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

    register_github_account_tools(
        mcp, lambda: {"accounts": []}, account_capabilities, READ_EXTERNAL
    )
    register_github_core_tools(
        mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL, policy
    )
    register_github_workflow_tools(
        mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL
    )
    register_github_review_tools(mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL)
    register_github_collab_tools(mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL)
    register_github_actions_tools(
        mcp, client_factory, READ_EXTERNAL, WRITE_EXTERNAL, DESTRUCTIVE_EXTERNAL
    )
    return mcp, provider


def gitlab_server() -> tuple[FastMCP, MagicMock]:
    provider = MagicMock(unsafe=True)
    provider.list_projects.return_value = {"projects": []}
    provider.create_project.return_value = {"created": True, "visibility": "private"}
    mcp = FastMCP("GitLab Unified Contract")

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


def mock_all_provider_methods(provider: MagicMock, source_directory: Path) -> None:
    """Intercept all bound provider methods: never perform external mutations."""
    source = "\n".join(p.read_text() for p in source_directory.glob("*tools.py"))
    method_names = set(
        re.findall(r"client_factory\(account_id\)\.([a-zA-Z_][a-zA-Z_0-9]*)\(", source)
    )
    for method in method_names:
        getattr(provider, method).return_value = {"ok": True, "method": method}


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
            self.assertEqual(len(response), 76)
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

    async def test_all_76_github_commands_dispatch_via_mcp(self) -> None:
        mcp, provider = github_server()
        mock_all_provider_methods(provider, Path(__file__).parents[1] / "src/briareus_github")
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
        self.assertEqual(len(tools), 76)

    async def test_all_38_gitlab_commands_dispatch_via_mcp(self) -> None:
        mcp, provider = gitlab_server()
        # The GitLab code is owned by a separate Hand.
        source_dir = Path(__file__).parents[2] / "gitlab/src/briareus_gitlab"
        mock_all_provider_methods(provider, source_dir)
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
        self.assertEqual(len(tools), 38)

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
                    "update_pull_branch_method",
                    {"account_id": "agent", "repository": "owner/repo", "number": 2},
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
            # Creating a repository or PR is not a repository source-history mutation.
            await client.call_tool(
                "create_repository",
                {"account_id": "agent", "owner": "owner", "name": "dram-repair"},
            )
            provider.create_repository.assert_called_once()

    async def test_gitlab_keeps_one_role_neutral_surface(self) -> None:
        mcp, provider = gitlab_server()
        tools = await mcp.list_tools()
        names = [tool.name for tool in tools]
        self.assertEqual(len(names), len(set(names)))
        # The two workflow-reading tools are registered separately by the real runtime.
        self.assertEqual(len(names), 38)
        self.assertFalse(any(name.startswith(("agent_", "reviewer_", "gitlab_")) for name in names))
        self.assertIn("create_project", names)
        async with Client(mcp) as client:
            await client.call_tool("create_project", {"account_id": "user", "name": "dram-repair"})
        provider.create_project.assert_called_once()
        self.assertEqual(provider.create_project.call_args.kwargs["visibility"], "private")


if __name__ == "__main__":
    unittest.main()
