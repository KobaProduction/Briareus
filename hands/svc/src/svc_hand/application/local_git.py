"""Authorize or push exactly the project-local checkout verified by the storage port."""

from dataclasses import dataclass, field
from typing import Protocol

from svc_hand.domain.local_git import LocalGitAuthorization, LocalGitPush, require_expected_sha


class LocalGitWorkspace(Protocol):
    def verify(self, destination: str, expected_remote: str, remote: str) -> str: ...
    def branch(self, workspace: str) -> str: ...
    def mutable_branch(self, branch: str) -> str: ...
    def validate_branch(self, workspace: str, branch: str) -> None: ...
    def push(
        self,
        workspace: str,
        remote_url: str,
        branch: str,
        set_upstream: bool,
        expected_sha: str,
        auth_scope: str,
        auth_header: str,
    ) -> None: ...
    def head(self, workspace: str) -> str: ...


@dataclass(frozen=True)
class AuthorizeLocalGit:
    storage: LocalGitWorkspace

    def execute(
        self, repository: str, destination: str, remote: str, expected_remote: str
    ) -> LocalGitAuthorization:
        workspace = self.storage.verify(destination, expected_remote, remote)
        return LocalGitAuthorization(
            repository, workspace, remote, expected_remote, self.storage.branch(workspace)
        )


@dataclass(frozen=True)
class PushLocalGit:
    storage: LocalGitWorkspace
    auth_scope: str = field(repr=False)
    auth_header: str = field(repr=False)

    def execute(
        self,
        repository: str,
        destination: str,
        remote: str,
        expected_remote: str,
        branch: str,
        set_upstream: bool,
        expected_remote_sha: str = "",
    ) -> LocalGitPush:
        workspace = self.storage.verify(destination, expected_remote, remote)
        selected = branch.strip() or self.storage.branch(workspace)
        selected = self.storage.mutable_branch(selected)
        self.storage.validate_branch(workspace, selected)
        require_expected_sha(expected_remote_sha)
        self.storage.push(
            workspace,
            expected_remote,
            selected,
            set_upstream,
            expected_remote_sha,
            self.auth_scope,
            self.auth_header,
        )
        return LocalGitPush(repository, workspace, remote, selected, self.storage.head(workspace))
