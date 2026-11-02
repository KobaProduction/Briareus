"""Canonical repository storage, remote refresh and linked worktree implementation."""

import hashlib
import os
import shutil
from pathlib import Path
from uuid import uuid4

from common.repository_checkout import resolve_workspace_destination
from modules.gitlab.policy import require_mutable_branch
from svc_hand.domain.local_git import CheckoutReceipt, CheckoutRequest
from svc_hand.infrastructure._repository_lock_binding import _RepositoryLockBinding

from .git_process import run_git
from .local_git import GitWorkspace, LocalCheckout


def canonical_repository(root: Path, clone_url: str) -> Path:
    digest = hashlib.sha256(clone_url.removesuffix(".git").casefold().encode()).hexdigest()
    directory = root / ".briareus-git" / "repositories"
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(root) or any(
        path.is_symlink() for path in (root / ".briareus-git", directory)
    ):
        raise ValueError("Project-local canonical repository required")
    return directory / (digest + ".git")


class GitCheckoutStorage(_RepositoryLockBinding):
    def __init__(
        self,
        checkout: LocalCheckout,
        destination: str,
        clone_url: str,
        auth_scope: str,
        auth_header: str,
    ) -> None:
        self.checkout = checkout
        self.root = checkout.workspace_root.resolve()
        self.target = resolve_workspace_destination(self.root, destination)
        if self.target.is_relative_to(self.root / ".briareus-git"):
            raise ValueError(
                "Canonical repository storage is reserved; select an agent worktree path"
            )
        self.canonical = canonical_repository(self.root, clone_url)
        self.destination = destination
        self.clone_url = clone_url
        self._auth_scope = auth_scope
        self._auth_header = auth_header

    def existing(self, mode: str) -> CheckoutReceipt | None:
        if self.canonical.is_symlink():
            raise ValueError("Canonical repository symlink rejected")
        if not self.target.exists():
            return None
        if mode == "git" and (self.target / ".git").is_file():
            GitWorkspace(self.checkout).verify(self.destination, self.clone_url, "origin")
            actual = Path(
                run_git(self.target, "rev-parse", "--path-format=absolute", "--git-common-dir")
            ).resolve()
            if actual == self.canonical.resolve():
                return CheckoutReceipt(
                    self.target.relative_to(self.root).as_posix(),
                    mode,
                    run_git(self.target, "branch", "--show-current"),
                    True,
                    self.canonical.relative_to(self.root).as_posix(),
                    True,
                    None,
                )
        raise ValueError("Destination exists; preserve it or choose a new worktree path")

    def initialize(self) -> None:
        if not self.canonical.exists():
            temporary = self.canonical.parent / (".clone-" + uuid4().hex)
            try:
                run_git(
                    self.root,
                    "clone",
                    "--bare",
                    "--template=",
                    "--",
                    self.clone_url,
                    str(temporary),
                    auth_scope=self._auth_scope,
                    auth_header=self._auth_header,
                )
                os.replace(temporary, self.canonical)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        elif run_git(self.canonical, "remote", "get-url", "origin").removesuffix(
            ".git"
        ) != self.clone_url.removesuffix(".git"):
            raise ValueError("Canonical remote mismatch")

    def refresh(self) -> None:
        # Only remote-tracking refs change; local agent branches remain intact.
        run_git(
            self.canonical,
            "fetch",
            "--no-tags",
            "origin",
            "+refs/heads/*:refs/remotes/origin/*",
            auth_scope=self._auth_scope,
            auth_header=self._auth_header,
        )

    def default_ref(self) -> str:
        advertised = run_git(
            self.canonical,
            "ls-remote",
            "--symref",
            "origin",
            "HEAD",
            auth_scope=self._auth_scope,
            auth_header=self._auth_header,
        )
        selected = next(
            (
                line.split()[1]
                for line in advertised.splitlines()
                if line.startswith("ref: ") and line.endswith("\tHEAD")
            ),
            None,
        )
        if not selected or not selected.startswith("refs/heads/"):
            raise ValueError("Remote default branch unavailable; select an explicit branch")
        return selected[len("refs/heads/") :]

    def resolve_ref(self, selected: str) -> str:
        if selected == "HEAD":
            return selected
        run_git(self.canonical, "check-ref-format", "refs/heads/" + selected)
        return "refs/remotes/origin/" + selected

    def validate_branch(self, branch: str) -> None:
        require_mutable_branch(branch, self.checkout.protected_branches)
        run_git(self.canonical, "check-ref-format", "refs/heads/" + branch)

    def create(self, branch: str, selected: str) -> None:
        self.target.parent.mkdir(parents=True, exist_ok=True)
        run_git(self.canonical, "worktree", "add", "-b", branch, "--", str(self.target), selected)

    def snapshot(self, branch: str) -> None:
        export = self.target.parent / (".snapshot-" + uuid4().hex)
        try:
            shutil.copytree(self.target, export, ignore=shutil.ignore_patterns(".git"))
            run_git(self.canonical, "worktree", "remove", "--", str(self.target))
            run_git(self.canonical, "branch", "-D", "--", branch)
            os.replace(export, self.target)
        finally:
            if export.exists():
                shutil.rmtree(export)

    def receipt(self, request: CheckoutRequest, branch: str) -> CheckoutReceipt:
        return CheckoutReceipt(
            self.target.relative_to(self.root).as_posix(),
            request.mode,
            branch if request.mode == "git" else None,
            request.mode == "git",
            self.canonical.relative_to(self.root).as_posix(),
            False,
            request.ref,
        )
