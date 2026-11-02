from __future__ import annotations

import urllib.parse
from typing import Protocol

from pydantic import BaseModel

from .application.history import RewriteCommand
from .application.linear_history import LinearHistoryResult, RewriteLinearHistory
from .domain.history import HistoryRewriteError
from .github_agent import GitHubAgentError
from .identity_views import (
    BranchPolicy,
    GitHubActor,
    MutationCapabilities,
    RepositoryCapabilities,
    RepositoryFacts,
    RepositoryPermissions,
)
from .infrastructure.history import GitHubHistory, HistoryClient
from .infrastructure.schemas.identity import AppRecord, UserRecord
from .infrastructure.schemas.installation import InstallationTokenReply
from .infrastructure.schemas.repository import GitCommitRecord, RepositoryRecord
from .transport_views import GitHubModelResponse

_GITHUB_API = "https://api.github.com"


class _GitHubHistoryHost(HistoryClient, Protocol):
    app_id: str
    auth_type: str
    token: str
    public_only: bool
    protected_branches: frozenset[str]

    def _assert_allowed(self, repository: str) -> str: ...

    def _app_jwt(self) -> str: ...

    def _installation_id(self, repository: str) -> int: ...

    def _any_installation_token(self) -> str: ...

    def _installation_permissions(self, repository: str) -> RepositoryPermissions: ...

    def _request_model[T: BaseModel](
        self,
        method: str,
        url: str,
        *,
        response_type: type[T],
        token: str | None = None,
        payload: BaseModel | None = None,
        auth_mode: str = "",
    ) -> GitHubModelResponse[T]: ...

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

    def _assert_branch_mutation_allowed(self, repository: str, branch: str) -> str: ...


class GitHubHistoryMixin:
    """Identity-aware history and branch-policy operations for GitHub App clients."""

    app_id: str

    def _agent_app_identity(self: _GitHubHistoryHost) -> GitHubActor:
        host = self
        app = host._request_model(
            "GET",
            f"{_GITHUB_API}/app",
            response_type=AppRecord,
            token=host._app_jwt(),
            auth_mode="github_app_jwt",
        ).data
        slug = app.slug
        login = f"{slug}[bot]"
        bot = host._request_model(
            "GET",
            f"{_GITHUB_API}/users/{urllib.parse.quote(login, safe='')}",
            response_type=UserRecord,
            token=host._any_installation_token(),
            auth_mode="installation",
        ).data
        return GitHubActor(
            source="current_agent_app",
            app_id=self.app_id,
            slug=slug,
            login=login,
            id=bot.id,
            name=login,
            email=f"{bot.id}+{login}@users.noreply.github.com",
        )

    def _installation_permissions(
        self: _GitHubHistoryHost, repository: str
    ) -> RepositoryPermissions:
        host = self
        installation_id = host._installation_id(repository)
        reply = host._request_model(
            "POST",
            f"{_GITHUB_API}/app/installations/{installation_id}/access_tokens",
            response_type=InstallationTokenReply,
            token=host._app_jwt(),
            auth_mode="github_app_jwt",
        ).data
        permissions = reply.permissions
        return RepositoryPermissions(
            contents=permissions.contents or "none",
            workflows=permissions.workflows or "none",
            pull_requests=permissions.pull_requests or "none",
            issues=permissions.issues or "none",
            actions=permissions.actions or "none",
            checks=permissions.checks or "none",
        )

    def capabilities(self: _GitHubHistoryHost, repository: str) -> RepositoryCapabilities:
        repository = self._assert_allowed(repository)
        repo = self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}",
            response_type=RepositoryRecord,
        ).data

        permissions: RepositoryPermissions
        app_id: str | None
        installation_id: int | None

        if self.public_only:
            contents_write = False
            permissions = RepositoryPermissions(
                contents="read",
                workflows="none",
                pull_requests="read",
                issues="read",
                actions="read",
                checks="read",
            )
            app_id = None
            installation_id = None
        elif self.token:
            repository_permissions = repo.permissions
            push = bool(repository_permissions.push or repository_permissions.admin)
            permissions = RepositoryPermissions(
                repository_push=push,
                repository_admin=bool(repository_permissions.admin),
                repository_maintain=bool(repository_permissions.maintain),
                contents="write" if push else "read",
                workflows="unknown",
                pull_requests="unknown",
                issues="unknown",
                actions="unknown",
                checks="unknown",
            )
            app_id = None
            installation_id = None
            contents_write = push
        else:
            installation_permissions = self._installation_permissions(repository)
            contents_write = installation_permissions.contents == "write"
            permissions = RepositoryPermissions(
                contents=installation_permissions.contents,
                workflows=installation_permissions.workflows,
                pull_requests=installation_permissions.pull_requests,
                issues=installation_permissions.issues,
                actions=installation_permissions.actions,
                checks=installation_permissions.checks,
            )
            app_id = self.app_id
            installation_id = self._installation_id(repository)

        return RepositoryCapabilities(
            repository=repository,
            allowed_repository=True,
            auth_type=self.auth_type,
            app_id=app_id,
            installation_id=installation_id,
            agent_identity=self._agent_app_identity(),
            repository_metadata=RepositoryFacts(
                default_branch=repo.default_branch or "",
                fork=repo.fork,
                archived=repo.archived,
            ),
            permissions=permissions,
            capabilities=MutationCapabilities(
                branch_delete=contents_write,
                force_ref_update=contents_write,
                history_identity_rewrite=contents_write,
            ),
            bridge_policy=BranchPolicy(
                reserved_branches=sorted(self.protected_branches),
                reserved_branch_mutation_allowed=False,
            ),
        )

    def _git_commit_object(self: _GitHubHistoryHost, repository: str, sha: str) -> GitCommitRecord:
        return self._repo_model(
            repository,
            "GET",
            f"/repos/{repository}/git/commits/{urllib.parse.quote(sha, safe='')}",
            response_type=GitCommitRecord,
        ).data

    @staticmethod
    def _identity_matches(commit: GitCommitRecord, name: str, email: str) -> bool:
        return all(
            actor is not None and actor.name == name and actor.email == email
            for actor in (commit.author, commit.committer)
        )

    def rewrite_branch_identity(
        self: _GitHubHistoryHost,
        repository: str,
        branch: str,
        expected_head_sha: str,
        *,
        identity_source: str = "current_agent_app",
        preserve_messages: bool = True,
        preserve_trees: bool = True,
        preserve_author_dates: bool = True,
        base_sha: str | None = None,
        max_commits: int = 100,
        dry_run: bool = True,
    ) -> LinearHistoryResult:
        command = RewriteCommand(
            repository,
            branch,
            expected_head_sha,
            identity_source,
            preserve_messages,
            preserve_trees,
            preserve_author_dates,
            max_commits,
            dry_run,
        )
        try:
            return RewriteLinearHistory(GitHubHistory(self, linear=True)).execute(command, base_sha)
        except HistoryRewriteError as exc:
            raise GitHubAgentError(str(exc)) from exc
