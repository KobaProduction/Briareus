"""Confined Git worktree inventory and compare-and-delete storage operations."""

from collections.abc import Iterator
from pathlib import Path

from svc_hand.domain.git_worktrees import WorktreeCandidate
from svc_hand.infrastructure._repository_lock_binding import _RepositoryLockBinding

from .git_process import run_git


class GitWorktreeStorage(_RepositoryLockBinding):
    def __init__(self, root: Path, canonical: Path) -> None:
        self.root = root
        self.canonical = canonical

    def exists(self) -> bool:
        return self.canonical.exists()

    def candidates(self, branch: str) -> Iterator[WorktreeCandidate]:
        listing = run_git(self.canonical, "worktree", "list", "--porcelain", "-z")
        for block in listing.split("\0\0"):
            fields = dict(line.split(" ", 1) for line in block.split("\0") if " " in line)
            if fields.get("branch") != "refs/heads/" + branch:
                continue
            path = Path(fields.get("worktree", "")).resolve()
            if (
                path == self.root
                or not path.is_relative_to(self.root)
                or path.is_relative_to(self.root / ".briareus-git")
            ):
                continue
            yield WorktreeCandidate(path.relative_to(self.root).as_posix(), fields.get("HEAD", ""))

    def dirty(self, path: str) -> bool:
        return bool(
            run_git(
                self.root / path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"
            )
        )

    def remove(self, path: str) -> None:
        # No force: Git independently refuses dirty or locked worktrees.
        run_git(self.canonical, "worktree", "remove", "--", str(self.root / path))

    def delete_branch(self, branch: str, expected_head: str) -> bool:
        try:
            current = run_git(self.canonical, "rev-parse", "refs/heads/" + branch)
            if current != expected_head:
                return False
            run_git(self.canonical, "update-ref", "-d", "refs/heads/" + branch, expected_head)
            return True
        except ValueError:
            return False
