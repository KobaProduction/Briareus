"""Git Data codec adapter retains the existing non-forced ref update and head recheck."""

from dataclasses import dataclass

from source_control.providers.github.application.mutations import BranchTransaction, CommitReceipt
from source_control.providers.github.domain.mutations import GitTreeEntry, TreeChange
from source_control.providers.github.git_transaction import GitHubGitDataTransactionClient
from source_control.providers.github.github_agent import GitHubAgentError

from ._repository_gate import _AllowedRepository
from .schemas.repository import GitBlobCreate, GitObjectId, GitTreeRecord, RepositoryFileIdentity


@dataclass(frozen=True, slots=True)
class GitMutations(_AllowedRepository[GitHubGitDataTransactionClient]):
    client: GitHubGitDataTransactionClient

    def resolve(self, repository: str, ref: str) -> str:
        return self.client._resolve_commit_sha(repository, ref)

    def begin(self, repository: str, branch: str, expected: str | None) -> BranchTransaction:
        return self.client._begin_git_transaction(repository, branch, expected)

    def tree(self, repository: str, sha: str) -> str:
        return self.client._resolve_commit_tree(repository, sha)

    def read_tree(self, repository: str, sha: str) -> tuple[GitTreeEntry, ...]:
        value = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/trees/{self.client._quote(sha)}",
            response_type=GitTreeRecord,
        ).data
        return tuple(
            GitTreeEntry(item.path, item.type, item.sha, item.mode, item.size)
            for item in value.tree
        )

    def entry(self, repository: str, tree: str, path: str) -> GitTreeEntry | None:
        parts = [part for part in path.strip("/").split("/") if part]
        if not parts:
            raise GitHubAgentError("path must not be empty")
        for index, part in enumerate(parts):
            entry = next(
                (item for item in self.read_tree(repository, tree) if item.path == part), None
            )
            if entry is None:
                return None
            if index == len(parts) - 1:
                return entry
            if entry.kind != "tree":
                return None
            tree = entry.sha
            if not tree:
                raise GitHubAgentError("Git tree entry has no sha")
        return None

    def commit(
        self, transaction: BranchTransaction, message: str, entries: tuple[TreeChange, ...]
    ) -> CommitReceipt:
        return self.client._commit_tree_entries(transaction, message, entries)

    def source_blob(self, repository: str, source_sha: str, path: str) -> str:
        source = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/contents/{self.client._path(path)}?ref={self.client._quote(source_sha)}",
            response_type=RepositoryFileIdentity,
        ).data
        if source.type != "file":
            raise GitHubAgentError(f"copy source is not a regular file: {path}")
        return source.sha

    def create_blob(self, repository: str, content: str, encoding: str) -> str:
        return self.client._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/git/blobs",
            response_type=GitObjectId,
            payload=GitBlobCreate(content=content, encoding=encoding),
        ).data.sha
