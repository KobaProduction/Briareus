"""Provider, marker, and optional local-Git codecs for the existing merge workflow."""

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from pydantic import BaseModel

from service_runtime.merge_policy import branch_choice, with_branch_choice
from source_control.providers.github.application.merge import (
    CleanupUnavailable,
    LocalWorktreeCleanup,
    MergeCommand,
    MergeReply,
    SourceHead,
)
from source_control.providers.github.application.review_gates import (
    RequiredChecksReceipt,
    RequiredReviewsReceipt,
)
from source_control.providers.github.domain.merge import PullSnapshot, RepositoryMergeSettings
from source_control.providers.github.github_agent import GitHubAgentError
from source_control.providers.github.transport_views import (
    GitHubAcknowledgement,
    GitHubModelResponse,
)

from ._repository_gate import _AllowedRepository
from .schemas.collaboration import PullMergeRequest, PullMergeResult, PullRequestRecord, PullUpdate
from .schemas.repository import (
    BranchProtectionRecord,
    GitReferenceRecord,
    RepositoryMergeSettingsRecord,
)


class MergeClient(Protocol):
    def _assert_allowed(self, repository: str) -> str: ...
    def _assert_mutable_branch(self, branch: str) -> str: ...
    def _quote(self, value: str) -> str: ...
    def _repo_model[T: BaseModel](
        self,
        repository: str,
        method: str,
        path: str,
        *,
        response_type: type[T],
        payload: BaseModel | None = None,
        query: BaseModel | None = None,
    ) -> GitHubModelResponse[T]: ...
    def _repo_inspect_model[T: BaseModel](
        self,
        repository: str,
        method: str,
        path: str,
        *,
        response_type: type[T],
        unavailable_statuses: set[int],
    ) -> T | None: ...
    def _repo_ack(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None = None,
    ) -> GitHubAcknowledgement: ...
    def assert_required_checks(self, repository: str, ref: str) -> RequiredChecksReceipt: ...


@runtime_checkable
class ReviewGate(Protocol):
    def assert_required_reviews(self, repository: str, number: int) -> RequiredReviewsReceipt: ...


@runtime_checkable
class SourceBranchDeletion(Protocol):
    def _delete_source_branch_cas(
        self, repository: str, branch: str, expected_head: str
    ) -> None: ...


@runtime_checkable
class MergedWorktreeCleanup(Protocol):
    def _cleanup_merged_worktrees(
        self, repository: str, branch: str, expected_head: str
    ) -> LocalWorktreeCleanup: ...


@dataclass(frozen=True, slots=True)
class GitHubMerge(_AllowedRepository[MergeClient]):
    client: MergeClient
    independent_reviews: bool

    def reviews(self, repository: str, number: int) -> None:
        if self.independent_reviews:
            if not isinstance(self.client, ReviewGate):
                raise GitHubAgentError("Independent review gate is unavailable")
            self.client.assert_required_reviews(repository, number)

    def pull(self, repository: str, number: int) -> PullSnapshot:
        pull = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/pulls/{number}",
            response_type=PullRequestRecord,
        ).data
        body = pull.body or ""
        return PullSnapshot(
            pull.head.repo.full_name if pull.head.repo else "",
            pull.base.repo.full_name if pull.base.repo else "",
            pull.head.sha,
            pull.head.ref,
            pull.base.ref,
            body,
            branch_choice(body),
        )

    def mutable(self, branch: str) -> None:
        self.client._assert_mutable_branch(branch)

    def settings(self, repository: str) -> RepositoryMergeSettings:
        repo = self.client._repo_model(
            repository, "GET", f"/repos/{repository}", response_type=RepositoryMergeSettingsRecord
        ).data
        return RepositoryMergeSettings(repo.default_branch or "", repo.delete_branch_on_merge)

    def protected(self, repository: str, branch: str) -> bool:
        value = self.client._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/branches/{self.client._quote(branch)}",
            response_type=BranchProtectionRecord,
        ).data
        return value.protected

    def checks(self, repository: str, head: str) -> None:
        self.client.assert_required_checks(repository, head)

    def record_choice(self, repository: str, number: int, body: str, choice: bool) -> None:
        self.client._repo_ack(
            repository,
            "PATCH",
            f"/repos/{repository}/pulls/{number}",
            payload=PullUpdate(body=with_branch_choice(body, choice)),
        )

    def merge(self, repository: str, command: MergeCommand, head: str) -> MergeReply:
        value = self.client._repo_model(
            repository,
            "PUT",
            f"/repos/{repository}/pulls/{command.number}/merge",
            response_type=PullMergeResult,
            payload=PullMergeRequest(
                merge_method=command.merge_method,
                sha=head,
                commit_title=command.commit_title or None,
                commit_message=command.commit_message or None,
            ),
        ).data
        return MergeReply(value.merged, value.sha or "", value.message or "")

    def source_head(self, repository: str, branch: str) -> SourceHead:
        try:
            value = self.client._repo_inspect_model(
                repository,
                "GET",
                f"/repos/{repository}/git/ref/heads/{self.client._quote(branch)}",
                response_type=GitReferenceRecord,
                unavailable_statuses={404},
            )
            return SourceHead(value is not None, value.object.sha if value is not None else "")
        except (GitHubAgentError, ValueError) as exc:
            raise CleanupUnavailable from exc

    def delete_cas(self, repository: str, branch: str, head: str) -> bool:
        if not isinstance(self.client, SourceBranchDeletion):
            return False
        try:
            self.client._delete_source_branch_cas(repository, branch, head)
            return True
        except (GitHubAgentError, ValueError) as exc:
            raise CleanupUnavailable from exc

    def cleanup_local(self, repository: str, branch: str, head: str) -> LocalWorktreeCleanup | None:
        if not isinstance(self.client, MergedWorktreeCleanup):
            return None
        return self.client._cleanup_merged_worktrees(repository, branch, head)
