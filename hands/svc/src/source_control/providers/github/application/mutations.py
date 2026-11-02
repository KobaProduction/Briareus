"""Build a complete mutation tree before the provider's existing guarded ref update."""

from dataclasses import dataclass
from typing import Protocol

from source_control.providers.github.application._bindings import _ProviderBinding
from source_control.providers.github.domain.mutations import (
    AtomicInput,
    CopiedFile,
    CopyItem,
    CopyPlan,
    GitTreeEntry,
    MutationError,
    TreeChange,
    copy_operation,
)


@dataclass(frozen=True, slots=True)
class BranchTransaction:
    repository: str
    branch: str
    branch_ref: str
    head_sha: str
    base_tree_sha: str


@dataclass(frozen=True, slots=True)
class CommitReceipt:
    previous_head_sha: str
    commit_sha: str
    tree_sha: str


@dataclass(frozen=True, slots=True)
class CopyResult:
    repository: str
    source_ref: str
    source_sha: str
    branch: str
    operation: str
    previous_head_sha: str
    commit_sha: str
    tree_sha: str
    copied: tuple[CopiedFile, ...]
    moved: tuple[CopiedFile, ...]


@dataclass(frozen=True, slots=True)
class AtomicResult:
    repository: str
    branch: str
    previous_head_sha: str
    commit_sha: str
    tree_sha: str
    changed_paths: tuple[str, ...]


class MutationProvider(Protocol):
    def allowed(self, repository: str) -> str: ...
    def resolve(self, repository: str, ref: str) -> str: ...
    def begin(self, repository: str, branch: str, expected: str | None) -> BranchTransaction: ...
    def tree(self, repository: str, sha: str) -> str: ...
    def entry(self, repository: str, tree: str, path: str) -> GitTreeEntry | None: ...
    def commit(
        self, transaction: BranchTransaction, message: str, entries: tuple[TreeChange, ...]
    ) -> CommitReceipt: ...
    def source_blob(self, repository: str, source_sha: str, path: str) -> str: ...
    def create_blob(self, repository: str, content: str, encoding: str) -> str: ...


class CopyFiles(_ProviderBinding[MutationProvider]):
    def execute(
        self,
        repository: str,
        source_ref: str,
        branch: str,
        message: str,
        copies: tuple[CopyItem, ...],
        expected: str | None,
        operation: str,
        *,
        overwrite: bool,
    ) -> CopyResult:
        repository = self.provider.allowed(repository)
        source_ref = source_ref.strip()
        if not source_ref:
            raise MutationError("source_ref must not be empty")
        if not copies:
            raise MutationError("copies must not be empty")
        selected = copy_operation(operation)
        source = self.provider.resolve(repository, source_ref)
        transaction = self.provider.begin(repository, branch, expected)
        if selected == "move" and source != transaction.head_sha:
            raise MutationError(
                "move requires source_ref to resolve to the current destination branch HEAD"
            )
        source_tree = (
            transaction.base_tree_sha
            if source == transaction.head_sha
            else self.provider.tree(repository, source)
        )
        plan = self.plan(
            repository,
            copies,
            CopyPlan(selected, overwrite=overwrite),
            source_tree,
            transaction.base_tree_sha,
        )
        committed = self.provider.commit(transaction, message, tuple(plan.entries))
        return CopyResult(
            repository,
            source_ref,
            source,
            transaction.branch,
            selected,
            committed.previous_head_sha,
            committed.commit_sha,
            committed.tree_sha,
            tuple(plan.processed) if selected == "copy" else (),
            tuple(plan.processed) if selected == "move" else (),
        )

    def plan(
        self,
        repository: str,
        copies: tuple[CopyItem, ...],
        plan: CopyPlan,
        source_tree: str,
        destination_tree: str,
    ) -> CopyPlan:
        for item in copies:
            normalized = plan.admit(item)
            source = self.provider.entry(repository, source_tree, normalized.source_path)
            if source is None:
                raise MutationError(f"source path is not a Git blob: {normalized.source_path}")
            source.require_source(normalized.source_path)
            destination = self.provider.entry(
                repository, destination_tree, normalized.destination_path
            )
            plan.append(normalized, source, destination)
        return plan


class AtomicChanges(_ProviderBinding[MutationProvider]):
    def entries(self, repository: str, changes: tuple[AtomicInput, ...]) -> tuple[TreeChange, ...]:
        result: list[TreeChange] = []
        resolved: dict[str, str] = {}
        for change in changes:
            path = change.path.strip("/")
            if change.operation == "delete":
                result.append(TreeChange(path, change.mode, None))
                continue
            if change.operation == "copy":
                ref = (change.source_ref or "").strip()
                if ref not in resolved:
                    resolved[ref] = self.provider.resolve(repository, ref)
                sha = self.provider.source_blob(
                    repository, resolved[ref], (change.source_path or "").strip("/")
                )
            else:
                sha = self.upload(repository, change)
            result.append(TreeChange(path, change.mode, sha))
        return tuple(result)

    def upload(self, repository: str, change: AtomicInput) -> str:
        if change.operation not in {"upsert", "create", "update"}:
            raise MutationError(f"unsupported change operation: {change.operation}")
        if change.content_base64 is not None:
            return self.provider.create_blob(repository, str(change.content_base64), "base64")
        return self.provider.create_blob(repository, str(change.content), "utf-8")

    def execute(
        self,
        repository: str,
        branch: str,
        message: str,
        changes: tuple[AtomicInput, ...],
        expected: str | None,
    ) -> AtomicResult:
        repository = self.provider.allowed(repository)
        if not changes:
            raise MutationError("changes must not be empty")
        transaction = self.provider.begin(repository, branch, expected)
        committed = self.provider.commit(transaction, message, self.entries(repository, changes))
        return AtomicResult(
            repository,
            transaction.branch,
            committed.previous_head_sha,
            committed.commit_sha,
            committed.tree_sha,
            tuple(change.path for change in changes),
        )
