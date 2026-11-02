"""Git Data mutations preserve blob identities and recheck the head before a non-forced update."""

import unittest
from dataclasses import dataclass, field

from pydantic import BaseModel

from modules.github.git_mutations import GitHubGitMutationClient
from modules.github.github_agent import GitHubAgentError
from modules.github.models import AtomicChange, CopySpec
from service_runtime.http_transport import HttpTransportResponse
from source_control.providers.github.infrastructure.schemas.repository import (
    GitBlobCreate,
    GitReferenceUpdate,
    GitTreeChange,
    GitTreeCreate,
)


def response(status: int, body: bytes) -> HttpTransportResponse:
    return HttpTransportResponse(status=status, headers={}, body=body, will_close=False)


@dataclass
class MutationWire(GitHubGitMutationClient):
    changed_head: bool = False
    events: list[tuple[str, str, BaseModel | None]] = field(default_factory=list)
    head_reads: int = 0

    def _assert_allowed(self, repository: str) -> str:
        return repository

    def _assert_mutable_branch(self, branch: str) -> str:
        return branch

    def _repo_transport(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None = None,
        allowed_errors: set[int] | None = None,
    ) -> HttpTransportResponse:
        del repository, allowed_errors
        self.events.append((method, path, payload))
        if method == "GET" and "/git/ref/heads/" in path:
            self.head_reads += 1
            head = "other" if self.changed_head and self.head_reads > 1 else "head"
            return response(200, f'{{"object":{{"sha":"{head}"}}}}'.encode())
        if method == "GET" and "/git/commits/" in path:
            return response(200, b'{"sha":"head","message":"fixture","tree":{"sha":"base"}}')
        if method == "GET" and "/git/trees/" in path:
            return response(
                200,
                b'{"sha":"base","tree":[{"path":"source","type":"blob",'
                b'"sha":"blob","mode":"100755","size":5}]}',
            )
        if method == "GET" and "/contents/" in path:
            return response(200, b'{"type":"file","sha":"copied-blob"}')
        if method == "GET" and "/commits/" in path:
            return response(200, b'{"sha":"head"}')
        if method == "POST":
            return response(201, b'{"sha":"created"}')
        if method == "PATCH":
            return response(200, b'{"object":{"sha":"created"}}')
        raise AssertionError(f"Unexpected fixture request: {method} {path}")

    def payloads(self, suffix: str) -> tuple[BaseModel, ...]:
        return tuple(
            payload
            for method, path, payload in self.events
            if method == "POST" and path.endswith(suffix) and payload is not None
        )


class MutationContractTests(unittest.TestCase):
    def test_copy_reuses_blob_and_preserves_mode_and_normalized_destination(self) -> None:
        client = MutationWire()
        receipt = client.copy_files(
            "owner/repo",
            "HEAD",
            "work",
            "copy",
            [
                CopySpec(source_path="/source", destination_path="nested//copied"),
            ],
            expected_head_sha="head",
        )
        self.assertEqual(receipt.copied[0].sha, "blob")
        self.assertEqual(receipt.copied[0].mode, "100755")
        self.assertEqual(receipt.copied[0].destination_path, "nested/copied")
        self.assertEqual(client.payloads("/git/blobs"), ())
        self.assertEqual(client.head_reads, 2)
        updates = [payload for method, _, payload in client.events if method == "PATCH"]
        self.assertEqual(updates, [GitReferenceUpdate(sha="created", force=False)])

    def test_move_deletes_original_using_original_mode(self) -> None:
        client = MutationWire()
        receipt = client.copy_files(
            "owner/repo",
            "HEAD",
            "work",
            "move",
            [
                CopySpec(source_path="source", destination_path="renamed", mode="100644"),
            ],
            operation="move",
        )
        self.assertEqual(receipt.copied, ())
        self.assertEqual(len(receipt.moved), 1)
        tree_payload = client.payloads("/git/trees")[0]
        self.assertEqual(
            tree_payload,
            GitTreeCreate(
                base_tree="base",
                tree=[
                    GitTreeChange(path="renamed", mode="100644", sha="blob"),
                    GitTreeChange(path="source", mode="100755", sha=None),
                ],
            ),
        )

    def test_duplicate_destinations_and_move_sources_prevent_tree_creation(self) -> None:
        scenarios = (
            ("copy", [CopySpec(source_path="source", destination_path="dest")] * 2),
            (
                "move",
                [
                    CopySpec(source_path="source", destination_path="left"),
                    CopySpec(source_path="source", destination_path="right"),
                ],
            ),
        )
        for operation, copies in scenarios:
            client = MutationWire()
            with self.subTest(operation=operation), self.assertRaises(GitHubAgentError):
                client.copy_files("owner/repo", "HEAD", "work", "copy", copies, operation=operation)
            self.assertEqual(client.payloads("/git/trees"), ())

    def test_concurrent_head_change_never_updates_ref(self) -> None:
        client = MutationWire(changed_head=True)
        with self.assertRaisesRegex(GitHubAgentError, "branch head changed before update"):
            client.copy_files(
                "owner/repo",
                "HEAD",
                "work",
                "copy",
                [
                    CopySpec(source_path="source", destination_path="dest"),
                ],
            )
        self.assertFalse(any(method == "PATCH" for method, _, _ in client.events))

    def test_atomic_changes_keep_encoding_and_resolve_copy_ref_once(self) -> None:
        client = MutationWire()
        receipt = client.commit_files(
            "owner/repo",
            "work",
            "atomic",
            [
                AtomicChange(path="text", content="hello"),
                AtomicChange(path="binary", content_base64="AA=="),
                AtomicChange(path="removed", operation="delete"),
                AtomicChange(
                    path="copied1", operation="copy", source_path="source", source_ref="tag"
                ),
                AtomicChange(
                    path="copied2", operation="copy", source_path="source", source_ref="tag"
                ),
            ],
        )
        self.assertEqual(receipt.changed_paths, ("text", "binary", "removed", "copied1", "copied2"))
        self.assertEqual(
            client.payloads("/git/blobs"),
            (
                GitBlobCreate(content="hello", encoding="utf-8"),
                GitBlobCreate(content="AA==", encoding="base64"),
            ),
        )
        refs = [
            path
            for method, path, _ in client.events
            if method == "GET" and path.endswith("/commits/tag")
        ]
        self.assertEqual(len(refs), 1)
