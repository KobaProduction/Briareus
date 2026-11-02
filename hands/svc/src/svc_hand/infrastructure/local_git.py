"""Confined checkout verification and ephemeral authenticated Git push."""

from collections.abc import Collection
from pathlib import Path
from typing import Protocol

from modules.gitlab.policy import require_mutable_branch
from svc_hand.domain.local_git import require_remote

from .git_process import run_git


class LocalCheckout(Protocol):
    workspace_root: Path

    @property
    def protected_branches(self) -> Collection[str]: ...
    def _local_git_path(self, destination: str) -> Path: ...


class GitWorkspace:
    def __init__(self, checkout: LocalCheckout) -> None:
        self._checkout = checkout
        self._root = checkout.workspace_root.resolve()

    def verify(self, destination: str, expected_remote: str, remote: str) -> str:
        require_remote(remote)
        target = self._checkout._local_git_path(destination)
        metadata = target / ".git"
        if metadata.is_symlink() or not (metadata.is_dir() or metadata.is_file()):
            raise ValueError("Project-local Git directory/worktree required")
        common = Path(
            run_git(target, "rev-parse", "--path-format=absolute", "--git-common-dir")
        ).resolve()
        if not common.is_relative_to(self._root):
            raise ValueError("Git metadata must remain inside current project")
        actual = run_git(target, "remote", "get-url", remote)
        if actual.removesuffix(".git") != expected_remote.removesuffix(".git"):
            raise ValueError("Checkout remote does not match approved repository")
        return target.relative_to(self._root).as_posix()

    def branch(self, workspace: str) -> str:
        return run_git(self._root / workspace, "branch", "--show-current")

    def mutable_branch(self, branch: str) -> str:
        return require_mutable_branch(branch, self._checkout.protected_branches)

    def validate_branch(self, workspace: str, branch: str) -> None:
        run_git(self._root / workspace, "check-ref-format", "refs/heads/" + branch)

    def push(
        self,
        workspace: str,
        remote_url: str,
        branch: str,
        set_upstream: bool,
        expected_sha: str,
        auth_scope: str,
        auth_header: str,
    ) -> None:
        arguments = ["push", "--porcelain"]
        if set_upstream:
            arguments.append("--set-upstream")
        if expected_sha:
            arguments.append(f"--force-with-lease=refs/heads/{branch}:{expected_sha}")
        arguments.extend(("--", remote_url, "HEAD:refs/heads/" + branch))
        run_git(self._root / workspace, *arguments, auth_scope=auth_scope, auth_header=auth_header)

    def head(self, workspace: str) -> str:
        return run_git(self._root / workspace, "rev-parse", "HEAD")
