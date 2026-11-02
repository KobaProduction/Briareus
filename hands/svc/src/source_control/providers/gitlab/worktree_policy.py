"""Unavailable local-worktree adapter for the private Node execution boundary."""

from typing import Never

from .errors import GitLabError


def unavailable_worktree(_project: str | int, _destination: str, _branch: str, _ref: str) -> Never:
    raise GitLabError("worktrees require the private Node Git runtime")
