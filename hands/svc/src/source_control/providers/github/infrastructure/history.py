"""Translate GitHub Git Data responses into immutable history records."""

import urllib.parse
from dataclasses import dataclass
from typing import Protocol

from pydantic import BaseModel

from source_control.providers.github.application.history import AgentIdentity, RewriteTarget
from source_control.providers.github.domain.history import GitCommit, GitIdentity, GitSignature
from source_control.providers.github.github_agent import GitHubAgentError
from source_control.providers.github.history_views import IdentitySource
from source_control.providers.github.identity_views import GitHubActor
from source_control.providers.github.transport_views import (
    GitHubAcknowledgement,
    GitHubModelResponse,
)

from .schemas.repository import (
    GitCommitCreate,
    GitCommitRecord,
    GitReferenceRecord,
    GitReferenceUpdate,
    GitSignatureRequest,
)


class HistoryClient(Protocol):
    def _assert_allowed(self, repository: str) -> str: ...
    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str: ...
    def _git_commit_object(self, repository: str, sha: str) -> GitCommitRecord: ...
    def _agent_app_identity(self) -> GitHubActor: ...
    def _repo_model[T: BaseModel](
        self,
        repository: str,
        method: str,
        path: str,
        *,
        response_type: type[T],
        payload: BaseModel | None = None,
        query: BaseModel | None = None,
    ) -> GitHubModelResponse[T]: ...
    def _repo_ack(
        self,
        repository: str,
        method: str,
        path: str,
        *,
        payload: BaseModel | None = None,
    ) -> GitHubAcknowledgement: ...


def signature(actor: IdentitySource | None) -> GitSignature:
    return (
        GitSignature(actor.name or "", actor.email or "", actor.date or "")
        if actor
        else GitSignature("", "", "")
    )


def git_commit(raw: GitCommitRecord, sha: str) -> GitCommit:
    return GitCommit(
        sha,
        raw.tree.sha,
        raw.message,
        tuple(parent.sha for parent in raw.parents),
        signature(raw.author),
        signature(raw.committer),
    )


@dataclass(frozen=True, slots=True)
class GitHubHistory:
    client: HistoryClient
    linear: bool = False

    def allowed_target(self, repository: str, branch: str) -> RewriteTarget:
        repository = self.client._assert_allowed(repository)
        return RewriteTarget(
            repository, self.client._assert_branch_mutation_allowed(repository, branch)
        )

    def head(self, target: RewriteTarget, *, confirming: bool = False) -> str:
        raw = self.client._repo_model(
            target.repository,
            "GET",
            f"/repos/{target.repository}/git/ref/heads/"
            f"{urllib.parse.quote(target.branch, safe='')}",
            response_type=GitReferenceRecord,
        ).data
        if not raw.object.sha:
            operation = "rewrite" if self.linear else "graph rewrite"
            message = (
                f"unable to re-check branch head before {operation}"
                if confirming
                else "unable to resolve branch head"
            )
            raise GitHubAgentError(message)
        return raw.object.sha

    def commit(self, target: RewriteTarget, sha: str) -> GitCommit:
        return git_commit(self.client._git_commit_object(target.repository, sha), sha)

    def identity(self) -> AgentIdentity:
        raw = self.client._agent_app_identity()
        return AgentIdentity(
            raw.source,
            raw.app_id,
            raw.slug,
            raw.login,
            raw.id,
            raw.name,
            raw.email,
        )

    def create(
        self,
        target: RewriteTarget,
        original: GitCommit,
        parents: tuple[str, ...],
        identity: GitIdentity,
        *,
        preserve_dates: bool,
    ) -> GitCommit:
        payload = GitCommitCreate(
            message=original.message,
            tree=original.tree,
            parents=list(parents),
            author=GitSignatureRequest(
                name=identity.name,
                email=identity.email,
                date=original.author.date or None if preserve_dates else None,
            ),
            committer=GitSignatureRequest(
                name=identity.name,
                email=identity.email,
                date=original.committer.date or None if preserve_dates else None,
            ),
        )
        created = self.client._repo_model(
            target.repository,
            "POST",
            f"/repos/{target.repository}/git/commits",
            response_type=GitCommitRecord,
            payload=payload,
        ).data
        return git_commit(created, created.sha)

    def replace_head(self, target: RewriteTarget, sha: str) -> None:
        self.client._repo_ack(
            target.repository,
            "PATCH",
            f"/repos/{target.repository}/git/refs/heads/"
            f"{urllib.parse.quote(target.branch, safe='')}",
            payload=GitReferenceUpdate(sha=sha, force=True),
        )
