from __future__ import annotations

from .application.mutations import BranchTransaction, CommitReceipt
from .base import GitHubRepositoryClientBase
from .domain.mutations import TreeChange
from .github_agent import GitHubAgentError
from .infrastructure.schemas.repository import (
    GitCommitCreate,
    GitCommitRecord,
    GitObjectId,
    GitReferenceRecord,
    GitReferenceUpdate,
    GitTreeChange,
    GitTreeCreate,
)


class GitHubGitDataTransactionClient(GitHubRepositoryClientBase):
    def _resolve_commit_sha(self, repository: str, ref: str) -> str:
        return self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/commits/{self._quote(ref)}",
            response_type=GitObjectId,
        ).data.sha

    def _resolve_commit_tree(self, repository: str, commit_sha: str) -> str:
        return self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{self._quote(commit_sha)}",
            response_type=GitCommitRecord,
        ).data.tree.sha

    def _begin_git_transaction(
        self,
        repository: str,
        branch: str,
        expected_head_sha: str | None = None,
    ) -> BranchTransaction:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        branch_ref = self._quote(branch)
        ref = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{branch_ref}",
            response_type=GitReferenceRecord,
        ).data
        head_sha = ref.object.sha
        if expected_head_sha and head_sha != expected_head_sha:
            raise GitHubAgentError(
                f"branch head changed: expected {expected_head_sha}, found {head_sha}"
            )
        return BranchTransaction(
            repository=repository,
            branch=branch,
            branch_ref=branch_ref,
            head_sha=head_sha,
            base_tree_sha=self._resolve_commit_tree(repository, head_sha),
        )

    def _commit_tree_entries(
        self,
        transaction: BranchTransaction,
        message: str,
        tree_entries: tuple[TreeChange, ...],
    ) -> CommitReceipt:
        repository = transaction.repository
        tree = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/git/trees",
            response_type=GitObjectId,
            payload=GitTreeCreate(
                base_tree=transaction.base_tree_sha,
                tree=[
                    GitTreeChange(path=entry.path, mode=entry.mode, sha=entry.sha)
                    for entry in tree_entries
                ],
            ),
        ).data
        commit = self._repo_model(
            repository,
            "POST",
            f"/repos/{repository}/git/commits",
            response_type=GitObjectId,
            payload=GitCommitCreate(message=message, tree=tree.sha, parents=[transaction.head_sha]),
        ).data
        current_ref = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/ref/heads/{transaction.branch_ref}",
            response_type=GitReferenceRecord,
        ).data
        current_head_sha = current_ref.object.sha
        if current_head_sha != transaction.head_sha:
            raise GitHubAgentError(
                "branch head changed before update: "
                f"expected {transaction.head_sha}, found {current_head_sha}"
            )
        self._repo_ack(
            repository,
            "PATCH",
            f"/repos/{repository}/git/refs/heads/{transaction.branch_ref}",
            payload=GitReferenceUpdate(sha=commit.sha, force=False),
        )
        return CommitReceipt(
            previous_head_sha=transaction.head_sha, commit_sha=commit.sha, tree_sha=tree.sha
        )
