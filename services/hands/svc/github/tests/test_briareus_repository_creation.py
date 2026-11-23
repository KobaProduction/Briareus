from __future__ import annotations

import unittest
from unittest.mock import patch

from briareus_github.github_agent import GitHubAgentError, GitHubRequestError
from briareus_github.github_identity import GitHubPrettyIdentityClient


class GitHubRepositoryCreationContracts(unittest.TestCase):
    @staticmethod
    def client(*, token: str = "") -> GitHubPrettyIdentityClient:
        return GitHubPrettyIdentityClient(
            app_id="123" if not token else "",
            private_key="test-only",
            token=token,
            auth_type="github_token" if token else "github_app",
            account_id="test-account",
        )

    @staticmethod
    def created(owner: str = "ArthurKoba", name: str = "dram-repair", private: bool = True) -> dict:
        return {
            "owner": {"login": owner},
            "name": name,
            "full_name": f"{owner}/{name}",
            "private": private,
            "default_branch": "main",
            "html_url": f"https://github.com/{owner}/{name}",
            "id": 1234,
        }

    def test_personal_installation_create_private(self) -> None:
        client = self.client()
        with (
            patch.object(client, "_app_jwt", return_value="jwt"),
            patch.object(
                client, "_installation_token_for_id", return_value="correct-token"
            ) as token,
            patch.object(client, "_request") as request,
        ):
            request.side_effect = [
                (200, {"id": 42, "account": {"login": "ArthurKoba", "type": "User"}}),
                (201, self.created()),
            ]
            result = client.create_repository("ArthurKoba", "dram-repair", auto_init=True)
        self.assertTrue(result["created"])
        self.assertTrue(result["private"])
        token.assert_called_once_with(42)
        self.assertEqual(
            request.call_args_list[0].args[1],
            "https://api.github.com/users/ArthurKoba/installation",
        )
        self.assertEqual(request.call_args_list[1].args[1], "https://api.github.com/user/repos")
        self.assertEqual(request.call_args_list[1].kwargs["token"], "correct-token")
        self.assertEqual(request.call_args_list[1].kwargs["payload"]["auto_init"], True)
        self.assertEqual(request.call_args_list[1].kwargs["payload"]["private"], True)

    def test_organization_installation_uses_exact_owner(self) -> None:
        client = self.client()
        with (
            patch.object(client, "_app_jwt", return_value="jwt"),
            patch.object(client, "_installation_token_for_id", return_value="org-token"),
            patch.object(client, "_request") as request,
        ):
            request.side_effect = [
                (404, {}),
                (200, {"id": 99, "account": {"login": "KobaProduction", "type": "Organization"}}),
                (201, self.created("KobaProduction")),
            ]
            result = client.create_repository("KobaProduction", "dram-repair")
        self.assertEqual(result["full_name"], "KobaProduction/dram-repair")
        self.assertEqual(
            request.call_args_list[-1].args[1], "https://api.github.com/orgs/KobaProduction/repos"
        )
        self.assertEqual(request.call_args_list[-1].kwargs["token"], "org-token")

    def test_wrong_owner_aborts_before_post(self) -> None:
        client = self.client()
        with (
            patch.object(client, "_app_jwt", return_value="jwt"),
            patch.object(client, "_request") as request,
        ):
            request.return_value = (
                200,
                {"id": 42, "account": {"login": "someone-else", "type": "User"}},
            )
            with self.assertRaisesRegex(GitHubAgentError, "does not match"):
                client.create_repository("ArthurKoba", "dram-repair")
        self.assertEqual(request.call_count, 1)

    def test_missing_installation_aborts_without_post(self) -> None:
        client = self.client()
        with (
            patch.object(client, "_app_jwt", return_value="jwt"),
            patch.object(client, "_request", return_value=(404, {})) as request,
            self.assertRaisesRegex(GitHubAgentError, "no installation"),
        ):
            client.create_repository("ArthurKoba", "dram-repair")
        self.assertEqual(request.call_count, 2)

    def test_explicit_public_allowed_and_verified(self) -> None:
        client = self.client(token="test-token")
        with (
            patch.object(client, "_token_identity", return_value={"login": "ArthurKoba"}),
            patch.object(
                client, "_request", return_value=(201, self.created(private=False))
            ) as request,
        ):
            result = client.create_repository("ArthurKoba", "dram-repair", private=False)
        self.assertIs(result["private"], False)
        self.assertEqual(request.call_args.kwargs["payload"]["private"], False)

    def test_token_organization_uses_org_endpoint(self) -> None:
        client = self.client(token="test-token")
        with (
            patch.object(client, "_token_identity", return_value={"login": "ArthurKoba"}),
            patch.object(
                client, "_request", return_value=(201, self.created("KobaProduction"))
            ) as request,
        ):
            client.create_repository("KobaProduction", "dram-repair")
        self.assertEqual(
            request.call_args.args[1], "https://api.github.com/orgs/KobaProduction/repos"
        )

    def test_invalid_owner_name_and_anonymous_rejected(self) -> None:
        client = self.client()
        with patch.object(client, "_request") as request:
            for owner, name in [
                ("owner/other", "valid"),
                ("ArthurKoba", "bad/repo"),
                ("ArthurKoba", ".."),
            ]:
                with self.assertRaises(GitHubRequestError):
                    client.create_repository(owner, name)
            request.assert_not_called()
        client.public_only = True
        with self.assertRaisesRegex(GitHubRequestError, "public"):
            client.create_repository("ArthurKoba", "dram-repair")

    def test_visibility_mismatch_reports_uncertain_state(self) -> None:
        client = self.client(token="test-token")
        with (
            patch.object(client, "_token_identity", return_value={"login": "ArthurKoba"}),
            patch.object(
                client, "_request", return_value=(201, self.created(private=False))
            ) as request,
            self.assertRaisesRegex(GitHubAgentError, "inspect the remote"),
        ):
            client.create_repository("ArthurKoba", "dram-repair")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
