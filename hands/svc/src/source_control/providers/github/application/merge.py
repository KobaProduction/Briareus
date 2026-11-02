"""Merge a pinned head once; post-merge cleanup never changes or replays that result."""

from dataclasses import dataclass
from typing import Literal, Protocol

from source_control.providers.github.application._bindings import _ProviderBinding
from source_control.providers.github.domain.merge import (
    MergeError,
    PullSnapshot,
    RepositoryMergeSettings,
    require_merge_request,
    require_method,
)


class CleanupUnavailable(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class MergeCommand:
    repository: str
    number: int
    delete_source_branch_after_merge: bool
    merge_method: str
    commit_title: str | None
    commit_message: str | None
    expected_head_sha: str | None


@dataclass(frozen=True, slots=True)
class MergeReply:
    merged: bool
    sha: str
    message: str


@dataclass(frozen=True, slots=True)
class SourceHead:
    exists: bool
    sha: str


@dataclass(frozen=True, slots=True)
class LocalWorktreeCleanup:
    removed_worktrees: tuple[str, ...]
    preserved_worktrees: tuple[str, ...]
    branch_deleted: bool
    status: str | None = None


@dataclass(frozen=True, slots=True)
class LocalCleanupFailed:
    status: Literal["cleanup_failed"] = "cleanup_failed"
    preserved: Literal[True] = True


@dataclass(frozen=True, slots=True)
class BranchCleanup:
    state: str
    local: LocalWorktreeCleanup | LocalCleanupFailed | None = None


@dataclass(frozen=True, slots=True)
class MergeReceipt:
    repository: str
    number: int
    merged: bool
    sha: str
    message: str
    merge_method: str
    delete_source_branch_after_merge: bool
    source_branch: str
    source_branch_state: str
    local_cleanup: LocalWorktreeCleanup | LocalCleanupFailed | None


class MergeProvider(Protocol):
    def reviews(self, repository: str, number: int) -> None: ...
    def allowed(self, repository: str) -> str: ...
    def pull(self, repository: str, number: int) -> PullSnapshot: ...
    def mutable(self, branch: str) -> None: ...
    def settings(self, repository: str) -> RepositoryMergeSettings: ...
    def protected(self, repository: str, branch: str) -> bool: ...
    def checks(self, repository: str, head: str) -> None: ...
    def record_choice(self, repository: str, number: int, body: str, choice: bool) -> None: ...
    def merge(self, repository: str, command: MergeCommand, head: str) -> MergeReply: ...
    def source_head(self, repository: str, branch: str) -> SourceHead: ...
    def delete_cas(self, repository: str, branch: str, head: str) -> bool: ...
    def cleanup_local(
        self, repository: str, branch: str, head: str
    ) -> LocalWorktreeCleanup | None: ...


class CleanupMergedSource(_ProviderBinding[MergeProvider]):
    def branch(self, repository: str, pull: PullSnapshot) -> str:
        try:
            current = self.provider.source_head(repository, pull.source_branch)
            if not current.exists:
                return "deleted"
            if current.sha != pull.head_sha:
                return "preserved_head_changed"
            deleted = self.provider.delete_cas(repository, pull.source_branch, pull.head_sha)
            return "deleted" if deleted else "cleanup_not_supported"
        except CleanupUnavailable:
            return "cleanup_failed"

    def after_merge(
        self, repository: str, pull: PullSnapshot, reply: MergeReply, *, delete: bool
    ) -> BranchCleanup:
        if not reply.merged:
            return BranchCleanup("merge_not_completed")
        state = self.branch(repository, pull) if delete else "kept"
        if state != "deleted":
            return BranchCleanup(state)
        try:
            local = self.provider.cleanup_local(repository, pull.source_branch, pull.head_sha)
        except Exception:
            return BranchCleanup(state, LocalCleanupFailed())
        return BranchCleanup(state, local)


class MergePullRequest(_ProviderBinding[MergeProvider]):
    def execute(self, command: MergeCommand) -> MergeReceipt:
        self.provider.reviews(command.repository, command.number)
        require_merge_request(command.delete_source_branch_after_merge, command.expected_head_sha)
        repository = self.provider.allowed(command.repository)
        require_method(command.merge_method)
        pull = self.provider.pull(repository, command.number)
        pull.require_owned(repository, command.expected_head_sha or "")
        self.require_source(repository, pull, delete=command.delete_source_branch_after_merge)
        self.provider.checks(repository, pull.head_sha)
        if pull.delete_choice is not command.delete_source_branch_after_merge:
            self.provider.record_choice(
                repository, command.number, pull.body, command.delete_source_branch_after_merge
            )
        reply = self.provider.merge(repository, command, pull.head_sha)
        cleanup = CleanupMergedSource(self.provider).after_merge(
            repository,
            pull,
            reply,
            delete=command.delete_source_branch_after_merge,
        )
        return MergeReceipt(
            repository,
            command.number,
            reply.merged,
            reply.sha,
            reply.message,
            command.merge_method,
            command.delete_source_branch_after_merge,
            pull.source_branch,
            cleanup.state,
            cleanup.local,
        )

    def require_source(self, repository: str, pull: PullSnapshot, *, delete: bool) -> None:
        if delete:
            self.provider.mutable(pull.source_branch)
            pull.require_source_distinct()
        self.provider.settings(repository).require_choice(pull, delete=delete)
        if delete and self.provider.protected(repository, pull.source_branch):
            raise MergeError("Cannot delete protected branch")
