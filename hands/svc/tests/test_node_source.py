"""Bounded Node provider dispatch and credential boundary checks."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from svc_hand.dispatch import SourceToolDispatch
from svc_hand.invocation_accounts import InvocationAccounts
from svc_hand.node_git import NodeGitHubClient, _git
from svc_hand.node_proxy import provider_connection


def account(**changes):
    return {"id": "account-1", "alias": "selected", "provider": "github",
            "auth_type": "github_token", "base_url": "https://api.github.com",
            "enabled": True, "created_at": "", "updated_at": "", **changes}


class NodeSourceTests(unittest.TestCase):
    def test_account_metadata_never_serializes_credential(self):
        port = InvocationAccounts([account(credential="fixture-private-token")])
        self.assertNotIn("fixture-private-token", json.dumps(port.list_accounts().to_json()))
        self.assertEqual(port.resolve_account("selected", provider="github").id, "account-1")
        with self.assertRaises(ValueError):
            port.resolve_account("another", provider="github")
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="gitlab")
        port.clear()
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="github")

    def test_public_account_metadata_cannot_execute_provider_effect(self):
        port = InvocationAccounts([account()])
        self.assertEqual(port.list_accounts().count, 1)
        with self.assertRaises(ValueError):
            port.resolve_account("selected", provider="github")

    def test_all_original_tools_and_policy_remain_live(self):
        dispatch = SourceToolDispatch(InvocationAccounts([]))
        self.assertEqual(len(dispatch.tools), 140)
        self.assertIn("github_agent_create_issue", dispatch.tools)
        self.assertIn("push_local_git", dispatch.tools)
        self.assertEqual(asyncio.run(dispatch.call("github_accounts", {}))["count"], 0)
        with self.assertRaises(ValueError):
            asyncio.run(dispatch.call("github_agent_put_file", {}))
        with self.assertRaises(ValueError):
            asyncio.run(dispatch.call("put_file", {}))
        dispatch.configure({"github_runtime": {"local_git_transport_enabled": False}})
        with self.assertRaises(ValueError):
            asyncio.run(dispatch.call("github_push_local_git", {}))
        dispatch.clear()

    def test_authorize_never_stores_provider_secret(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            target = root / "checkout"
            subprocess.run(["git", "init", "--template=", str(target)], check=True, capture_output=True)
            subprocess.run(["git", "-C", str(target), "remote", "add", "origin",
                            "https://github.com/owner/repository.git"], check=True)
            client = NodeGitHubClient(token="fixture-private-token", account_id="account-1", auth_type="github_token")
            client.workspace_root = root
            result = client.authorize_local_git("owner/repository", "checkout")
            self.assertEqual(result["credential_storage"], "none")
            self.assertFalse((target / ".git" / "koba-credentials").exists())
            self.assertNotIn("fixture-private-token", (target / ".git" / "config").read_text())
            with self.assertRaises(ValueError):
                client.authorize_local_git("owner/another", "checkout")

    def test_git_disables_hooks_helpers_and_only_uses_ephemeral_header(self):
        completed = subprocess.CompletedProcess([], 0, stdout=b"ok", stderr=b"")
        with patch("svc_hand.node_git.subprocess.run", return_value=completed) as run:
            _git(Path("/project-data"), "push", "--", "https://github.com/owner/repo.git",
                 auth_scope="https://github.com/", auth_header="Authorization: Basic fixture")
        env = run.call_args.kwargs["env"]
        configs = {env[f"GIT_CONFIG_KEY_{i}"]: env[f"GIT_CONFIG_VALUE_{i}"]
                   for i in range(int(env["GIT_CONFIG_COUNT"]))}
        self.assertEqual(configs["core.hooksPath"], "/dev/null")
        self.assertEqual(configs["credential.helper"], "")
        self.assertEqual(configs["core.fsmonitor"], "false")
        self.assertEqual(env["GIT_ALLOW_PROTOCOL"], "https")
        self.assertNotIn("fixture", " ".join(run.call_args.args[0]))

    def test_provider_has_no_direct_egress_fallback(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(ValueError):
                provider_connection("https://api.github.com")
        with patch.dict(os.environ, {"HTTPS_PROXY": "http://module-egress:8080"}, clear=True):
            connection = provider_connection("https://api.github.com")
            self.assertEqual(connection.host, "module-egress")
            self.assertEqual(connection._tunnel_host, "api.github.com")
            connection.close()
            for url in ("http://api.github.com", "https://api.github.com:8443", "https://token@example.com"):
                with self.assertRaises(ValueError):
                    provider_connection(url)
            with self.assertRaises(ValueError):
                provider_connection("https://api.github.com", verify_tls=False)
