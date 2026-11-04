from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from briareus_json_values import JsonObject, JsonValue, json_array, json_int, json_str
from pydantic import ValidationError

from .git_transaction import GitBranchTransaction, GitHubGitDataTransactionClient
from .github_agent import GitHubAgentError
from .models import AtomicChange, CopySpec


@dataclass(frozen=True)
class _Blob:
    sha: str
    mode: str
    size: int


@dataclass(frozen=True)
class _CopyPlan:
    entries: list[JsonObject]
    processed: list[JsonObject]


def _copy_paths(item: CopySpec) -> tuple[str, str]:
    source = "/".join(part for part in item.source_path.strip("/").split("/") if part)
    destination = "/".join(part for part in item.destination_path.strip("/").split("/") if part)
    if not source or not destination:
        raise GitHubAgentError("every copy requires source_path and destination_path")
    if source == destination:
        raise GitHubAgentError("source_path and destination_path must be different")
    return source, destination


def _copy_specs(copies: Sequence[CopySpec | Mapping[str, JsonValue]]) -> list[CopySpec]:
    if not copies:
        raise GitHubAgentError("copies must not be empty")
    try:
        return [
            item if isinstance(item, CopySpec) else CopySpec.model_validate(item) for item in copies
        ]
    except ValidationError as exc:
        raise GitHubAgentError("invalid copy specification") from exc


class GitHubGitMutationClient(GitHubGitDataTransactionClient):
    def copy_files(
        self,
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: Sequence[CopySpec | Mapping[str, JsonValue]],
        expected_head_sha: str | None = None,
        operation: str = "copy",
        overwrite: bool = False,
    ) -> JsonObject:
        """Copy or move existing Git blobs without transferring file contents."""
        repository = self._assert_allowed(repository)
        source_ref = source_ref.strip()
        operation = operation.strip().casefold()
        if not source_ref:
            raise GitHubAgentError("source_ref must not be empty")
        normalized_copies = _copy_specs(copies)
        if operation not in {"copy", "move"}:
            raise GitHubAgentError("operation must be 'copy' or 'move'")

        source_sha = self._resolve_commit_sha(repository, source_ref)
        transaction = self._begin_git_transaction(
            repository,
            branch,
            expected_head_sha,
        )
        if operation == "move" and source_sha != transaction.head_sha:
            raise GitHubAgentError(
                "move requires source_ref to resolve to the current destination branch HEAD"
            )

        source_tree = transaction.base_tree_sha
        if source_sha != transaction.head_sha:
            source_tree = self._resolve_commit_tree(repository, source_sha)

        plan = self._copy_plan(transaction, source_tree, normalized_copies, operation, overwrite)

        committed = self._commit_tree_entries(transaction, message, plan.entries)
        return {
            "repository": repository,
            "source_ref": source_ref,
            "source_sha": source_sha,
            "branch": transaction.branch,
            "operation": operation,
            "previous_head_sha": committed.previous_head_sha,
            "commit_sha": committed.commit_sha,
            "tree_sha": committed.tree_sha,
            "copied": json_array(
                plan.processed if operation == "copy" else [],
                context="GitHub copied files",
            ),
            "moved": json_array(
                plan.processed if operation == "move" else [],
                context="GitHub moved files",
            ),
        }

    def _copy_blob(self, repository: str, tree: str, path: str) -> _Blob:
        source = self._tree_entry_at_path(repository, tree, path)
        if source is None or json_str(source.get("type")) != "blob":
            raise GitHubAgentError(f"source path is not a Git blob: {path}")
        sha = json_str(source.get("sha"))
        mode = json_str(source.get("mode"))
        if not sha or not mode:
            raise GitHubAgentError(f"source blob is missing sha or mode: {path}")
        return _Blob(sha, mode, json_int(source.get("size")))

    def _assert_copy_destination(
        self, transaction: GitBranchTransaction, path: str, overwrite: bool
    ) -> None:
        destination = self._tree_entry_at_path(
            transaction.repository, transaction.base_tree_sha, path
        )
        if destination is None:
            return
        if not overwrite:
            raise GitHubAgentError(f"destination_path already exists: {path}")
        if json_str(destination.get("type")) != "blob":
            raise GitHubAgentError(f"destination_path is not a blob: {path}")

    def _copy_plan(
        self,
        transaction: GitBranchTransaction,
        source_tree: str,
        copies: list[CopySpec],
        operation: str,
        overwrite: bool,
    ) -> _CopyPlan:
        entries: list[JsonObject] = []
        processed: list[JsonObject] = []
        destinations: set[str] = set()
        move_sources: set[str] = set()
        for item in copies:
            source, destination = _copy_paths(item)
            if destination in destinations:
                raise GitHubAgentError(f"duplicate destination_path: {destination}")
            destinations.add(destination)
            if operation == "move" and source in move_sources:
                raise GitHubAgentError(f"duplicate move source_path: {source}")
            move_sources.add(source)
            blob = self._copy_blob(transaction.repository, source_tree, source)
            mode = item.mode or blob.mode
            self._assert_copy_destination(transaction, destination, overwrite)
            entries.append({"path": destination, "mode": mode, "type": "blob", "sha": blob.sha})
            if operation == "move":
                entries.append({"path": source, "mode": blob.mode, "type": "blob", "sha": None})
            processed.append(
                {
                    "source_path": source,
                    "destination_path": destination,
                    "sha": blob.sha,
                    "mode": mode,
                    "size": blob.size,
                }
            )
        return _CopyPlan(entries, processed)

    def commit_files(
        self,
        repository: str,
        branch: str,
        message: str,
        changes: Sequence[AtomicChange | Mapping[str, JsonValue]],
        expected_head_sha: str | None = None,
    ) -> JsonObject:
        repository = self._assert_allowed(repository)
        if not changes:
            raise GitHubAgentError("changes must not be empty")
        try:
            normalized_changes = [
                item if isinstance(item, AtomicChange) else AtomicChange.model_validate(item)
                for item in changes
            ]
        except ValidationError as exc:
            raise GitHubAgentError("invalid atomic change") from exc

        transaction = self._begin_git_transaction(
            repository,
            branch,
            expected_head_sha,
        )
        copy_ref_cache: dict[str, str] = {}
        tree_entries = [
            self._atomic_change_entry(repository, change, copy_ref_cache)
            for change in normalized_changes
        ]

        committed = self._commit_tree_entries(transaction, message, tree_entries)
        return {
            "repository": repository,
            "branch": transaction.branch,
            "previous_head_sha": committed.previous_head_sha,
            "commit_sha": committed.commit_sha,
            "tree_sha": committed.tree_sha,
            "changed_paths": [change.path for change in normalized_changes],
        }

    def _atomic_change_entry(
        self, repository: str, change: AtomicChange, copy_ref_cache: dict[str, str]
    ) -> JsonObject:
        path = change.path.strip("/")
        operation = change.operation
        mode = change.mode
        if operation == "delete":
            return {"path": path, "mode": mode, "type": "blob", "sha": None}
        if operation == "copy":
            blob_sha = self._atomic_copy_sha(repository, change, copy_ref_cache)
        else:
            if operation not in {"upsert", "create", "update"}:
                raise GitHubAgentError(f"unsupported change operation: {operation}")
            blob_sha = self._atomic_content_sha(repository, change)
        return {"path": path, "mode": mode, "type": "blob", "sha": blob_sha}

    def _atomic_copy_sha(
        self, repository: str, change: AtomicChange, copy_ref_cache: dict[str, str]
    ) -> str:
        source_path = (change.source_path or "").strip("/")
        source_ref = (change.source_ref or "").strip()
        source_sha = copy_ref_cache.get(source_ref)
        if source_sha is None:
            source_sha = self._resolve_commit_sha(repository, source_ref)
            copy_ref_cache[source_ref] = source_sha
        _, source = self._repo_request(
            repository,
            "GET",
            f"/repos/{repository}/contents/{self._path(source_path)}?ref={self._quote(source_sha)}",
        )
        if not isinstance(source, dict) or source.get("type") != "file":
            raise GitHubAgentError(f"copy source is not a regular file: {source_path}")
        blob_sha = json_str(source.get("sha"))
        if not blob_sha:
            raise GitHubAgentError(f"copy source has no blob sha: {source_path}")
        return blob_sha

    def _atomic_content_sha(self, repository: str, change: AtomicChange) -> str:
        encoded = change.content_base64
        blob_payload: JsonObject
        if encoded is not None:
            blob_payload = {"content": str(encoded), "encoding": "base64"}
        else:
            blob_payload = {"content": str(change.content), "encoding": "utf-8"}
        _, blob = self._repo_request(
            repository,
            "POST",
            f"/repos/{repository}/git/blobs",
            payload=blob_payload,
        )
        if not isinstance(blob, dict):
            raise GitHubAgentError("GitHub did not return a blob sha")
        blob_sha = json_str(blob.get("sha"))
        if not blob_sha:
            raise GitHubAgentError("GitHub did not return a blob sha")
        return blob_sha
