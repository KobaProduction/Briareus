"""Composition of validated provider inputs with typed copy and atomic-commit use cases."""

from collections.abc import Sequence

from .application.mutations import AtomicChanges, AtomicResult, CopyFiles, CopyResult
from .domain.mutations import AtomicInput, CopyItem, MutationError
from .git_transaction import GitHubGitDataTransactionClient
from .github_agent import GitHubAgentError
from .infrastructure.mutations import GitMutations
from .models import AtomicChange, CopySpec


class GitHubGitMutationClient(GitHubGitDataTransactionClient):
    def copy_files(
        self,
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: Sequence[CopySpec],
        expected_head_sha: str | None = None,
        operation: str = "copy",
        overwrite: bool = False,
    ) -> CopyResult:
        repository = self._assert_allowed(repository)
        inputs = tuple(
            CopyItem(item.source_path, item.destination_path, item.mode) for item in copies
        )
        try:
            return CopyFiles(GitMutations(self)).execute(
                repository,
                source_ref,
                branch,
                message,
                inputs,
                expected_head_sha,
                operation,
                overwrite=overwrite,
            )
        except MutationError as exc:
            raise GitHubAgentError(str(exc)) from exc

    def commit_files(
        self,
        repository: str,
        branch: str,
        message: str,
        changes: Sequence[AtomicChange],
        expected_head_sha: str | None = None,
    ) -> AtomicResult:
        repository = self._assert_allowed(repository)
        inputs = tuple(
            AtomicInput(
                item.operation,
                item.path,
                item.mode,
                item.content,
                item.content_base64,
                item.source_path,
                item.source_ref,
            )
            for item in changes
        )
        try:
            return AtomicChanges(GitMutations(self)).execute(
                repository, branch, message, inputs, expected_head_sha
            )
        except MutationError as exc:
            raise GitHubAgentError(str(exc)) from exc
