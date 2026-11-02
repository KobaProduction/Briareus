"""Existing canonical Git repository lock delegation; no lock state or namespace."""

from contextlib import AbstractContextManager
from pathlib import Path

from .git_process import repository_lock


class _RepositoryLockBinding:
    __slots__ = ()
    canonical: Path

    def lock(self) -> AbstractContextManager[None]:
        return repository_lock(self.canonical)
