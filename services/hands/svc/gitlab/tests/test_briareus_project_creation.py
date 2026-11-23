from __future__ import annotations

import unittest
from unittest.mock import patch

from briareus_gitlab.errors import GitLabError
from briareus_gitlab.gitlab_client import GitLabClient
from briareus_gitlab.models import GitLabProfile, GitLabResponse


class GitLabProjectCreationContracts(unittest.TestCase):
    @staticmethod
    def client(*, anonymous: bool = False, auth_type: str = "private_token") -> GitLabClient:
        profile = GitLabProfile(
            account_id="test-account",
            alias="gitlab-test",
            base_url="https://gitlab.example.com",
            auth_type=auth_type,
        )
        profile.bind_token("test-token")
        return GitLabClient(profile, anonymous_only=anonymous)

    @staticmethod
    def created(namespace: str = "gitlab-user", visibility: str = "private") -> GitLabResponse:
        return GitLabResponse(
            status=201,
            headers={},
            data={
                "id": 123,
                "path": "dram-repair",
                "visibility": visibility,
                "path_with_namespace": f"{namespace}/dram-repair",
                "web_url": f"https://gitlab.example.com/{namespace}/dram-repair",
                "default_branch": "main",
            },
        )

    def test_default_private_personal_project(self) -> None:
        client = self.client()
        with patch.object(client, "request", return_value=self.created()) as request:
            result = client.create_project("dram-repair", initialize_with_readme=True)
        self.assertTrue(result["created"])
        self.assertEqual(result["visibility"], "private")
        self.assertEqual(request.call_args.args, ("POST", "/projects"))
        self.assertNotIn("namespace_id", request.call_args.kwargs["payload"])
        self.assertEqual(request.call_args.kwargs["payload"]["initialize_with_readme"], True)

    def test_group_namespace_resolved_before_creation(self) -> None:
        client = self.client()
        with patch.object(
            client,
            "request",
            side_effect=[
                GitLabResponse(status=200, headers={}, data={"id": 56, "full_path": "group/sub"}),
                self.created("group/sub"),
            ],
        ) as request:
            result = client.create_project("DRAM Repair", path="dram-repair", namespace="group/sub")
        self.assertEqual(result["path_with_namespace"], "group/sub/dram-repair")
        self.assertEqual(request.call_args_list[0].args, ("GET", "/namespaces/group%2Fsub"))
        self.assertEqual(request.call_args_list[1].kwargs["payload"]["namespace_id"], 56)

    def test_wrong_namespace_fails_before_creation(self) -> None:
        client = self.client()
        with (
            patch.object(
                client,
                "request",
                return_value=GitLabResponse(
                    status=200, headers={}, data={"id": 56, "full_path": "other"}
                ),
            ) as request,
            self.assertRaisesRegex(GitLabError, "did not match"),
        ):
            client.create_project("dram-repair", namespace="group/sub")
        request.assert_called_once()

    def test_invalid_input_anonymous_and_job_token_rejected(self) -> None:
        client = self.client()
        with patch.object(client, "request") as request:
            for kw in [{"path": "slash/bad"}, {"visibility": "secret"}, {"path": "bad-"}]:
                with self.assertRaises(GitLabError):
                    client.create_project("dram-repair", **kw)
            request.assert_not_called()
        for client in (self.client(anonymous=True), self.client(auth_type="job_token")):
            with patch.object(client, "request") as request:
                with self.assertRaisesRegex(GitLabError, "authorized GitLab user token"):
                    client.create_project("dram-repair")
                request.assert_not_called()

    def test_visibility_mismatch_reports_uncertain_state(self) -> None:
        client = self.client()
        with (
            patch.object(
                client, "request", return_value=self.created(visibility="public")
            ) as request,
            self.assertRaisesRegex(GitLabError, "inspect the remote"),
        ):
            client.create_project("dram-repair")
        request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
