from __future__ import annotations

import unittest
from unittest.mock import patch

from briareus_account_contracts import AccountList, AccountPublic, ResolvedAccount
from briareus_control_panel_client.control_panel_client import ControlPanelClient
from briareus_github.github_agent import GitHubAgentError
from briareus_github.github_identity import GitHubPrettyIdentityClient
from briareus_github.settings import GitHubPolicySettings
from briareus_github.tool_context import GitHubRuntimeContext
from briareus_json_values import json_member_array, json_object


def missing_installation(repository: str = "someone/public") -> GitHubAgentError:
    return GitHubAgentError(f"repository {repository!r} is not installed for GitHub App 123")


def role_client() -> GitHubPrettyIdentityClient:
    return GitHubPrettyIdentityClient(
        app_id="123", private_key="test-only", account_id="agent", auth_type="github_app"
    )


def public_client() -> GitHubPrettyIdentityClient:
    return GitHubPrettyIdentityClient(account_id="public", auth_type="public", public_only=True)


class PublicRepositoryFallbackContracts(unittest.TestCase):
    def test_public_read_only_after_app_installation_miss(self) -> None:
        role = role_client()
        public = public_client()
        role.public_read_client = lambda: public
        with (
            patch.object(role, "_installation_token", side_effect=missing_installation()),
            patch.object(public, "_assert_public_repository") as guard,
            patch.object(
                public, "_repo_request", return_value=(200, {"content": "aGVsbG8="})
            ) as read,
        ):
            result = role._repo_request(
                "someone/public", "GET", "/repos/someone/public/contents/README.md"
            )
        self.assertEqual(result[0], 200)
        guard.assert_called_once_with("someone/public")
        read.assert_called_once_with(
            "someone/public",
            "GET",
            "/repos/someone/public/contents/README.md",
            payload=None,
            allowed_errors=None,
        )

    def test_installed_reads_use_role_token_not_public_reader(self) -> None:
        role = role_client()
        public = public_client()
        role.public_read_client = lambda: public
        with (
            patch.object(role, "_installation_token", return_value="app-installation-token"),
            patch.object(role, "_request", return_value=(200, {"name": "README"})) as request,
            patch.object(public, "_repo_request") as fallback,
        ):
            result = role._repo_request(
                "someone/installed", "GET", "/repos/someone/installed/contents/README.md"
            )
        self.assertEqual(result[0], 200)
        self.assertEqual(request.call_args.kwargs["token"], "app-installation-token")
        fallback.assert_not_called()

    def test_noninstalled_mutations_do_not_fall_back(self) -> None:
        role = role_client()
        public = public_client()
        role.public_read_client = lambda: public
        with (
            patch.object(role, "_installation_token", side_effect=missing_installation()),
            patch.object(public, "_repo_request") as fallback,
        ):
            with self.assertRaisesRegex(GitHubAgentError, "not installed"):
                role._repo_request("someone/public", "DELETE", "/repos/someone/public/git/refs/x")
            fallback.assert_not_called()

    def test_private_repository_is_rejected_before_fallback_read(self) -> None:
        role = role_client()
        public = public_client()
        role.public_read_client = lambda: public
        with (
            patch.object(role, "_installation_token", side_effect=missing_installation()),
            patch.object(
                public,
                "_assert_public_repository",
                side_effect=GitHubAgentError(
                    "public GitHub access cannot read private repositories"
                ),
            ),
            patch.object(public, "_repo_request") as fallback,
        ):
            with self.assertRaisesRegex(GitHubAgentError, "private repositories"):
                role._repo_request("someone/private", "GET", "/repos/someone/private/contents/x")
            fallback.assert_not_called()

    def test_status_identifies_public_fallback_under_role(self) -> None:
        role = role_client()
        public = public_client()
        role.public_read_client = lambda: public
        with (
            patch.object(role, "_installation_id", side_effect=missing_installation()),
            patch.object(role, "_app_identity", return_value={"login": "agent[bot]"}),
            patch.object(public, "_assert_public_repository"),
            patch.object(public, "status", return_value={"status": "ok", "auth_type": "public"}),
        ):
            result = role.status("someone/public")
        self.assertEqual(result["access_mode"], "public_read_fallback")
        self.assertEqual(result["auth_type"], "github_app")
        self.assertEqual(result["selected_account_id"], "agent")

    def test_default_public_selector_uses_anonymous_not_legacy_token(self) -> None:
        settings = GitHubPolicySettings(_env_file=None)
        management = object.__new__(ControlPanelClient)
        context = GitHubRuntimeContext(management, settings)
        with patch.object(ControlPanelClient, "list_accounts") as accounts:
            public = context.client("public")
        self.assertTrue(public.public_only)
        self.assertFalse(public.token)
        accounts.assert_not_called()

    def test_both_role_identities_receive_read_only_fallback(self) -> None:
        management = object.__new__(ControlPanelClient)
        context = GitHubRuntimeContext(management, GitHubPolicySettings(_env_file=None))

        def resolve(selector: str, *, provider: str) -> ResolvedAccount:
            self.assertEqual(provider, "github")
            return ResolvedAccount(
                id=selector,
                alias=selector,
                provider="github",
                auth_type="github_app",
                base_url="https://api.github.com",
                credential="test-only",
                external_id="123",
                created_at="",
                updated_at="v1",
            )

        with patch.object(ControlPanelClient, "resolve_account", side_effect=resolve):
            for alias in ("koba-ai-agent", "koba-ai-reviewer"):
                with self.subTest(alias=alias):
                    role = context.client(alias)
                    self.assertIsNotNone(role.public_read_client)
                    assert role.public_read_client is not None
                    self.assertTrue(role.public_read_client().public_only)

    def test_public_capability_report_does_not_grant_write(self) -> None:
        management = object.__new__(ControlPanelClient)
        context = GitHubRuntimeContext(management, GitHubPolicySettings(_env_file=None))
        role = role_client()
        public = public_client()
        with (
            patch.object(context, "_client", return_value=role),
            patch.object(context, "_public_client", return_value=public),
            patch.object(role, "account_capabilities", return_value={"auth_type": "github_app"}),
            patch.object(role, "capabilities", side_effect=missing_installation()),
            patch.object(public, "_assert_public_repository"),
            patch.object(
                public,
                "capabilities",
                return_value={
                    "permissions": {"contents": "read"},
                    "capabilities": {"branch_delete": False, "force_ref_update": False},
                },
            ),
        ):
            result = context.account_capabilities("agent", "someone/public")
        repository = json_object(result["repository"])
        self.assertEqual(repository["access_mode"], "public_read_fallback")
        self.assertEqual(json_object(repository["permissions"])["contents"], "read")
        self.assertFalse(json_object(repository["capabilities"])["branch_delete"])

    def test_legacy_token_alias_is_not_advertised(self) -> None:
        management = object.__new__(ControlPanelClient)
        context = GitHubRuntimeContext(management, GitHubPolicySettings(_env_file=None))

        def account(alias: str, auth_type: str) -> AccountPublic:
            return AccountPublic.model_validate(
                {
                    "id": alias,
                    "alias": alias,
                    "provider": "github",
                    "auth_type": auth_type,
                    "base_url": "https://api.github.com",
                    "enabled": True,
                    "created_at": "",
                    "updated_at": "",
                }
            )

        with patch.object(
            ControlPanelClient,
            "list_accounts",
            return_value=AccountList(
                accounts=[
                    account("authenticated", "github_token"),
                    account("koba-ai-agent", "github_app"),
                ],
                count=2,
            ),
        ):
            result = context.list_accounts()
        self.assertEqual(result["count"], 2)
        self.assertEqual(
            [json_object(item)["alias"] for item in json_member_array(result, "accounts")],
            ["koba-ai-agent", "public"],
        )
