"""Bounded Node provider dispatch and credential boundary checks."""

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from mcp.types import CallToolRequestParams
from test_account_lease import account

from node_protocol.provider_context import GitRuntimePolicy, InvocationPolicies, ProjectAccount
from svc_hand.dispatch import SourceToolDispatch
from svc_hand.infrastructure.git_process import git_environment, run_git
from svc_hand.invocation_accounts import InvocationAccounts
from svc_hand.node_git import NodeGitHubClient
from svc_hand.node_proxy import provider_connection


class NodeSourceTests(unittest.TestCase):
    def test_account_metadata_never_serializes_credential(self) -> None:
        row = account()
        port = InvocationAccounts([row])
        self.assertNotIn("fixture-private-token", port.list_accounts().model_dump_json())
        self.assertEqual(port.resolve_account("selected", provider="github").id, str(row.id))
        with self.assertRaises(ValueError):
            port.resolve_account("another", provider="github")
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="gitlab")
        port.clear()
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="github")

    def test_public_account_metadata_cannot_execute_provider_effect(self) -> None:
        public = ProjectAccount.model_validate_json(
            account().model_dump_json(exclude={"credential"})
        )
        port = InvocationAccounts([public])
        self.assertEqual(port.list_accounts().count, 1)
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="github")

    def test_all_original_tools_and_policy_remain_live(self) -> None:
        dispatch = SourceToolDispatch(InvocationAccounts([]))
        self.assertEqual(len(dispatch.tools), 142)
        self.assertIn("source_control", dispatch.tools)
        self.assertIn("source_control_capabilities", dispatch.tools)
        self.assertIn("github_agent_create_issue", dispatch.tools)
        self.assertIn("push_local_git", dispatch.tools)
        result = asyncio.run(
            dispatch.call(CallToolRequestParams(name="github_accounts", arguments={}))
        )
        assert result.structured_content is not None
        self.assertEqual(result.structured_content["count"], 0)
        with self.assertRaises(ValueError):
            asyncio.run(
                dispatch.call(CallToolRequestParams(name="github_agent_put_file", arguments={}))
            )
        with self.assertRaises(ValueError):
            asyncio.run(dispatch.call(CallToolRequestParams(name="put_file", arguments={})))
        dispatch.configure(
            InvocationPolicies(
                github_runtime=GitRuntimePolicy(
                    local_first_guidance=True,
                    local_git_transport_enabled=False,
                    remote_source_mutations_enabled=False,
                )
            )
        )
        with self.assertRaises(ValueError):
            asyncio.run(
                dispatch.call(CallToolRequestParams(name="github_push_local_git", arguments={}))
            )
        dispatch.clear()

    def test_authorize_never_stores_provider_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "checkout"
            run_git(root, "init", "--template=", str(target))
            run_git(target, "remote", "add", "origin", "https://github.com/owner/repository.git")
            row = account()
            assert row.credential is not None
            client = NodeGitHubClient(
                token=row.credential, account_id=str(row.id), auth_type="github_token"
            )
            client.workspace_root = root
            result = client.authorize_local_git("owner/repository", "checkout")
            self.assertEqual(result.credential_storage, "none")
            self.assertFalse((target / ".git" / "koba-credentials").exists())
            self.assertNotIn("fixture-private-token", (target / ".git" / "config").read_text())
            with self.assertRaises(ValueError):
                client.authorize_local_git("owner/another", "checkout")

    def test_git_disables_hooks_helpers_and_only_uses_ephemeral_header(self) -> None:
        scope, header = "https://github.com/", "Authorization: Basic fixture"
        env = dict(git_environment(scope, header).variables)
        configs = {
            env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
            for i in range(int(env["GIT_CONFIG_COUNT"]))
        }
        self.assertEqual(configs["core.hooksPath"], "/dev/null")
        self.assertEqual(configs["credential.helper"], "")
        self.assertEqual(configs["core.fsmonitor"], "false")
        self.assertEqual(env["GIT_ALLOW_PROTOCOL"], "https")
        self.assertEqual(configs["http.https://github.com/.extraHeader"], header)
        with tempfile.TemporaryDirectory() as temporary:
            version = run_git(Path(temporary), "--version", auth_scope=scope, auth_header=header)
            self.assertTrue(version.startswith("git version "))
            self.assertNotIn("fixture", version)

    def test_provider_has_no_direct_egress_fallback(self) -> None:
        with patch.dict(os.environ, {}, clear=True), self.assertRaises(ValueError):
            provider_connection("https://api.github.com")
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://module-egress:8080"}, clear=True):
            with patch("hand_runtime.provider_egress.ProviderConnection.set_tunnel") as tunnel:
                connection = provider_connection("https://api.github.com")
            tunnel.assert_called_once_with("api.github.com", 443)
            self.assertEqual(connection.host, "module-egress")
            connection.close()
            for url in (
                "http://api.github.com",
                "https://api.github.com:8443",
                "https://token@example.com",
            ):
                with self.assertRaises(ValueError):
                    provider_connection(url)
            with self.assertRaises(ValueError):
                provider_connection("https://api.github.com", verify_tls=False)
