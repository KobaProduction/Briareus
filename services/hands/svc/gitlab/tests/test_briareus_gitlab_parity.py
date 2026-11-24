from __future__ import annotations

import base64
import hashlib
import unittest
from unittest.mock import MagicMock, patch

from briareus_gitlab.errors import GitLabError, GitLabRequestError
from briareus_gitlab.gitlab_client import GitLabClient
from briareus_gitlab.models import GitLabProfile, GitLabResponse
from briareus_gitlab.reviews import DiffPosition
from briareus_http_transport.http_transport import HttpTransportError, HttpTransportResponse
from briareus_json_values import JsonValue

PROJECT = "group/sub/project"
ROOT = "/projects/group%2Fsub%2Fproject"
MR = ROOT + "/merge_requests/7"
SHA = "a" * 40


def response(data: JsonValue, status: int = 200) -> GitLabResponse:
    return GitLabResponse(status=status, headers={}, data=data)


def provider(*, anonymous: bool = False, protected: frozenset[str] = frozenset()) -> GitLabClient:
    profile = GitLabProfile(
        account_id="test-account",
        alias="test",
        base_url="https://gitlab.example.com",
        auth_type="private_token",
    )
    profile.bind_token("test-only")
    return GitLabClient(profile, anonymous_only=anonymous, protected_branches=protected)


class GitLabFileAndTagContracts(unittest.TestCase):
    def test_binary_read_is_pinned_to_exact_raw_bytes(self) -> None:
        client = provider()
        raw = b"\xff\x00\x80\n"
        with (
            patch.object(
                client,
                "request",
                return_value=response(
                    {
                        "encoding": "base64",
                        "content": "dGV4dA==",
                        "commit_id": SHA,
                        "blob_id": "blob",
                        "size": len(raw),
                    }
                ),
            ) as request,
            patch.object(client, "request_bytes", return_value=raw) as raw_request,
        ):
            result = client.get_file(PROJECT, "dir/file.bin", "main", "base64")
        request.assert_called_once_with(
            "GET", ROOT + "/repository/files/dir%2Ffile.bin", query={"ref": "main"}
        )
        raw_request.assert_called_once_with(
            ROOT + "/repository/files/dir%2Ffile.bin/raw", query={"ref": SHA}
        )
        self.assertEqual(base64.b64decode(str(result["content_base64"])), raw)
        self.assertNotIn("content", result)

    def test_binary_write_and_last_commit_guard(self) -> None:
        client = provider()
        with patch.object(client, "request", side_effect=[response({}), response({})]) as request:
            client.put_file(
                PROJECT, "a.bin", "/wA=", "write", "feature", "base64", last_commit_id=SHA
            )
        self.assertEqual(request.call_args.args, ("PUT", ROOT + "/repository/files/a.bin"))
        self.assertEqual(
            request.call_args.kwargs["payload"],
            {
                "branch": "feature",
                "content": "/wA=",
                "commit_message": "write",
                "encoding": "base64",
                "last_commit_id": SHA,
            },
        )

    def test_bad_base64_and_protected_branch_block_before_request(self) -> None:
        client = provider(protected=frozenset({"main"}))
        with patch.object(client, "request") as request:
            with self.assertRaisesRegex(GitLabError, "base64"):
                client.put_file(PROJECT, "a.bin", "!!", "write", "feature", "base64")
            with self.assertRaisesRegex(GitLabError, "protected"):
                client.put_file(PROJECT, "a.bin", "/wA=", "write", "main", "base64")
            request.assert_not_called()

    def test_tag_routes_encode_project_and_tag_names(self) -> None:
        client = provider()
        with patch.object(
            client,
            "request",
            side_effect=[
                response([{"name": "v1", "commit": {"id": SHA}}]),
                response({"name": "release/v1", "commit": {"id": SHA}}, 201),
                response({}, 204),
            ],
        ) as request:
            listed = client.list_tags(PROJECT, 20, 2)
            created = client.create_tag(PROJECT, "release/v1", SHA, "release")
            client.delete_tag(PROJECT, "release/v1")
        self.assertEqual(listed["tags"], [{"name": "v1", "sha": SHA}])
        self.assertEqual(listed["page"], 2)
        self.assertEqual(
            created,
            {"repository": PROJECT, "tag": "release/v1", "target_sha": SHA, "annotated": True},
        )
        self.assertEqual(request.call_args_list[0].kwargs["query"], {"per_page": 20, "page": 2})
        self.assertEqual(
            request.call_args_list[1].kwargs["payload"],
            {"tag_name": "release/v1", "ref": SHA, "message": "release"},
        )
        self.assertEqual(
            request.call_args_list[2].args, ("DELETE", ROOT + "/repository/tags/release%2Fv1")
        )


class GitLabReviewContracts(unittest.TestCase):
    def test_approval_pins_head_and_withdrawal_uses_native_endpoint(self) -> None:
        client = provider()
        with patch.object(client, "request", return_value=response({})) as request:
            with self.assertRaises(GitLabRequestError):
                client.set_merge_request_approval(PROJECT, 7, True)
            request.assert_not_called()
            client.set_merge_request_approval(PROJECT, 7, True, SHA)
            request.assert_called_once_with("POST", MR + "/approve", payload={"sha": SHA})
            request.reset_mock()
            client.set_merge_request_approval(PROJECT, 7, False)
            request.assert_called_once_with("POST", MR + "/unapprove", payload=None)

    def test_inline_discussion_uses_exact_diff_refs(self) -> None:
        client = provider()
        position = DiffPosition(
            base_sha="base",
            start_sha="start",
            head_sha=SHA,
            old_path="src/a.py",
            new_path="src/b.py",
            new_line=5,
        )
        refs = {"base_sha": "base", "start_sha": "start", "head_sha": SHA}
        with patch.object(
            client,
            "request",
            side_effect=[
                response({"diff_refs": refs}),
                response({"id": "thread"}, 201),
            ],
        ) as request:
            client.create_review_thread(PROJECT, 7, "review", position)
        self.assertEqual(request.call_args.args, ("POST", MR + "/discussions"))
        self.assertEqual(
            request.call_args.kwargs["payload"]["position"],
            {
                **refs,
                "old_path": "src/a.py",
                "new_path": "src/b.py",
                "new_line": 5,
                "position_type": "text",
            },
        )
        with patch.object(
            client,
            "request",
            return_value=response(
                {
                    "diff_refs": {**refs, "head_sha": "different"},
                }
            ),
        ) as request:
            with self.assertRaisesRegex(GitLabRequestError, "diff version changed"):
                client.create_review_thread(PROJECT, 7, "review", position)
            request.assert_called_once()

    def test_review_thread_mutations_use_native_ids(self) -> None:
        client = provider()
        thread = MR + "/discussions/thread%2Fid"
        with patch.object(client, "request", return_value=response({})) as request:
            client.reply_to_review_thread(PROJECT, 7, "thread/id", "reply")
            client.update_review_comment(PROJECT, 7, "thread/id", 12, "edited")
            client.set_review_thread_resolved(PROJECT, 7, "thread/id", False)
            client.set_reviewers(PROJECT, 7, [])
        self.assertEqual(request.call_args_list[0].args, ("POST", thread + "/notes"))
        self.assertEqual(request.call_args_list[1].args, ("PUT", thread + "/notes/12"))
        self.assertEqual(request.call_args_list[2].kwargs["payload"], {"resolved": False})
        self.assertEqual(request.call_args_list[3].kwargs["payload"], {"reviewer_ids": []})

    def test_note_routing_and_explicit_deletion(self) -> None:
        client = provider()
        with patch.object(client, "request", return_value=response({}, 204)) as request:
            with self.assertRaises(GitLabRequestError):
                client.delete_note(PROJECT, "issue", 7, 3)
            request.assert_not_called()
            client.delete_note(PROJECT, "issue", 7, 3, True)
            request.assert_called_once_with("DELETE", ROOT + "/issues/7/notes/3")
            request.reset_mock()
            client.update_note(PROJECT, "merge_request", 7, 3, "edit")
            request.assert_called_once_with("PUT", MR + "/notes/3", payload={"body": "edit"})

    def test_rebase_checks_head_project_and_reserved_branch(self) -> None:
        client = provider(protected=frozenset({"main"}))
        valid = {
            "sha": SHA,
            "source_project_id": 1,
            "target_project_id": 1,
            "source_branch": "feature",
        }
        for invalid in (
            {**valid, "sha": "changed"},
            {**valid, "source_project_id": 2},
            {**valid, "source_branch": "main"},
        ):
            with patch.object(client, "request", return_value=response(invalid)) as request:
                with self.assertRaises(GitLabError):
                    client.rebase_merge_request(PROJECT, 7, SHA)
                request.assert_called_once()
        with patch.object(
            client,
            "request",
            side_effect=[
                response(valid),
                response({"rebase_in_progress": True}, 202),
            ],
        ) as request:
            result = client.rebase_merge_request(PROJECT, 7, SHA)
        self.assertEqual(request.call_args.args, ("PUT", MR + "/rebase"))
        self.assertEqual(result["rebase"], {"rebase_in_progress": True})

    def test_graphql_mutations_resolve_project_path_and_reject_errors(self) -> None:
        client = provider()
        with patch.object(
            client,
            "request",
            side_effect=[
                response({"sha": SHA}),
                response({"path_with_namespace": PROJECT}),
                response(
                    {
                        "data": {
                            "mergeRequestRequestChanges": {
                                "errors": [],
                                "mergeRequest": {"iid": "7"},
                            }
                        }
                    }
                ),
            ],
        ) as request:
            client.request_review_changes("42", 7, SHA)
        self.assertEqual(request.call_args.args, ("POST", "/"))
        self.assertTrue(request.call_args.kwargs["graphql"])
        self.assertEqual(
            request.call_args.kwargs["payload"]["variables"],
            {
                "input": {"projectPath": PROJECT, "iid": "7"},
            },
        )
        with (
            patch.object(
                client,
                "request",
                side_effect=[
                    response({"path_with_namespace": PROJECT}),
                    response(
                        {
                            "data": {
                                "mergeRequestSetDraft": {
                                    "errors": ["denied"],
                                    "mergeRequest": None,
                                }
                            }
                        }
                    ),
                ],
            ),
            self.assertRaisesRegex(GitLabError, "rejected"),
        ):
            client.set_merge_request_draft("42", 7, False)


class GitLabPipelineContracts(unittest.TestCase):
    def test_pipeline_and_job_dispatch(self) -> None:
        client = provider()
        with patch.object(client, "request", return_value=response({})) as request:
            client.create_pipeline(PROJECT, "main", {"TEST": "yes"}, {"test": True})
            self.assertEqual(request.call_args.args, ("POST", ROOT + "/pipeline"))
            self.assertEqual(
                request.call_args.kwargs["payload"],
                {
                    "ref": "main",
                    "variables": [{"key": "TEST", "value": "yes"}],
                    "inputs": {"test": True},
                },
            )
            for action in ("retry", "cancel", "play"):
                client.control_job(PROJECT, 10, action)
                self.assertEqual(request.call_args.args, ("POST", ROOT + f"/jobs/10/{action}"))

    def test_artifact_result_preserves_bytes_and_hash(self) -> None:
        client = provider()
        raw = b"\xff\x00zip"
        with patch.object(client, "request_bytes", return_value=raw) as request:
            result = client.download_job_artifacts(PROJECT, 10, "out/a b.zip", 100)
            request.assert_called_once_with(
                ROOT + "/jobs/10/artifacts/out/a%20b.zip",
                max_bytes=100,
            )
            with self.assertRaises(GitLabError):
                client.download_job_artifacts(PROJECT, 10, "../secret")
            request.assert_called_once()
        self.assertEqual(result["content_base64"], base64.b64encode(raw).decode())
        self.assertEqual(result["sha256"], hashlib.sha256(raw).hexdigest())

    def test_mutations_do_not_retry_or_fall_back_anonymously(self) -> None:
        client = provider()
        with patch.object(
            client._transport, "request", side_effect=HttpTransportError("lost")
        ) as req:
            with self.assertRaises(GitLabError):
                client.create_pipeline(PROJECT, "main")
            req.assert_called_once()
            self.assertEqual(req.call_args.kwargs["reconnect_retries"], 0)
        with patch.object(
            client._transport,
            "request",
            return_value=HttpTransportResponse(
                status=403,
                headers={},
                body=b"denied",
                will_close=False,
            ),
        ) as req:
            with self.assertRaises(GitLabError):
                client.create_pipeline(PROJECT, "main")
            req.assert_called_once()
        anonymous = provider(anonymous=True)
        with patch.object(anonymous._transport, "request") as req:
            with self.assertRaisesRegex(GitLabError, "read-only"):
                anonymous.create_pipeline(PROJECT, "main")
            req.assert_not_called()

    def test_download_redirect_has_no_provider_credentials(self) -> None:
        client = provider()
        conn = MagicMock()
        conn.getresponse.return_value.status = 302
        conn.getresponse.return_value.getheader.return_value = (
            "https://cdn.example.org/file?signature=x"
        )
        with (
            patch.object(client, "_new_connection", return_value=conn),
            patch(
                "briareus_gitlab.api.download_public_https", return_value=b"archive"
            ) as redirected,
        ):
            self.assertEqual(client.request_bytes(ROOT + "/jobs/10/artifacts"), b"archive")
        self.assertEqual(conn.request.call_args.kwargs["headers"]["PRIVATE-TOKEN"], "test-only")
        redirected.assert_called_once_with(
            "https://cdn.example.org/file?signature=x", 8 * 1024 * 1024
        )
        conn.close.assert_called_once()
