"""Best-effort local cleanup after the provider merge has already completed."""

from collections.abc import Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Protocol

from modules.github.application.merge import LocalWorktreeCleanup
from svc_hand.domain.git_worktrees import WorktreeCandidate


class WorktreeStorage(Protocol):
    def exists(self) -> bool: ...
    def lock(self) -> AbstractContextManager[None]: ...
    def candidates(self, branch: str) -> Iterable[WorktreeCandidate]: ...
    def dirty(self, path: str) -> bool: ...
    def remove(self, path: str) -> None: ...
    def delete_branch(self, branch: str, expected_head: str) -> bool: ...


@dataclass(frozen=True)
class CleanupMergedWorktrees:
    storage: WorktreeStorage

    def execute(self, branch: str, expected_head: str) -> LocalWorktreeCleanup:
        removed: list[str] = []
        preserved: list[str] = []
        branch_deleted = False
        if not self.storage.exists():
            return LocalWorktreeCleanup((), (), False)
        try:
            with self.storage.lock():
                self._cleanup(branch, expected_head, removed, preserved)
                if not preserved:
                    branch_deleted = self.storage.delete_branch(branch, expected_head)
        except (ValueError, OSError):
            return LocalWorktreeCleanup(
                tuple(removed), tuple(preserved), branch_deleted, "cleanup_incomplete"
            )
        return LocalWorktreeCleanup(tuple(removed), tuple(preserved), branch_deleted)

    def _cleanup(
        self, branch: str, expected_head: str, removed: list[str], preserved: list[str]
    ) -> None:
        for candidate in self.storage.candidates(branch):
            # Avoid even running status for a changed head, as in the original path.
            if candidate.head != expected_head or not candidate.removable(
                expected_head, dirty=self.storage.dirty(candidate.relative_path)
            ):
                preserved.append(candidate.relative_path)
                continue
            try:
                self.storage.remove(candidate.relative_path)
                removed.append(candidate.relative_path)
            except ValueError:
                preserved.append(candidate.relative_path)
