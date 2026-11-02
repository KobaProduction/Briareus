"""A merged worktree can be removed only at the exact merged head and when clean."""

from dataclasses import dataclass


@dataclass(frozen=True)
class WorktreeCandidate:
    relative_path: str
    head: str

    def removable(self, merged_head: str, *, dirty: bool) -> bool:
        return self.head == merged_head and not dirty
