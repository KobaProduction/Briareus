from __future__ import annotations

import base64

from .base import GitHubRepositoryClientBase
from .content_views import (
    DirectoryEntry,
    DirectoryListing,
    RepositoryBinaryFile,
    RepositoryCodeSearch,
    RepositoryContentDelete,
    RepositoryContentWrite,
    RepositoryTextFile,
)
from .github_agent import GitHubAgentError
from .infrastructure.schemas.content import (
    CodeSearchQuery,
    CodeSearchResult,
    ContentDelete,
    ContentEntries,
    ContentFile,
    ContentMutationResult,
    ContentWrite,
)
from .infrastructure.schemas.repository import RepositoryFileIdentity


class GitHubContentApiClient(GitHubRepositoryClientBase):
    def list_directory(
        self,
        repository: str,
        path: str = "",
        ref: str | None = None,
    ) -> DirectoryListing:
        repository = self._assert_allowed(repository)
        suffix = self._path(path)
        endpoint = f"/repos/{repository}/contents" + (f"/{suffix}" if suffix else "")
        if ref:
            endpoint += "?ref=" + self._quote(ref)
        result = self._repo_model(
            repository, "GET", endpoint, response_type=ContentEntries
        ).data.root
        entries = [
            DirectoryEntry(
                name=item.name, path=item.path, type=item.type, size=item.size, sha=item.sha
            )
            for item in result
        ]
        return DirectoryListing(repository=repository, path=path, ref=ref, entries=entries)

    def get_file(self, repository: str, path: str, ref: str | None = None) -> RepositoryTextFile:
        repository = self._assert_allowed(repository)
        endpoint = f"/repos/{repository}/contents/{self._path(path)}"
        if ref:
            endpoint += "?ref=" + self._quote(ref)
        result = self._repo_model(repository, "GET", endpoint, response_type=ContentFile).data
        if result.type != "file":
            raise GitHubAgentError("path is not a regular GitHub repository file")
        if result.encoding != "base64":
            raise GitHubAgentError(f"unsupported GitHub content encoding: {result.encoding}")
        decoded = base64.b64decode(result.content).decode("utf-8", "replace")
        return RepositoryTextFile(
            repository=repository,
            path=result.path,
            sha=result.sha,
            size=result.size,
            content=decoded,
        )

    def get_binary_file(
        self,
        repository: str,
        path: str,
        ref: str | None = None,
    ) -> RepositoryBinaryFile:
        repository = self._assert_allowed(repository)
        endpoint = f"/repos/{repository}/contents/{self._path(path)}"
        if ref:
            endpoint += "?ref=" + self._quote(ref)
        result = self._repo_model(repository, "GET", endpoint, response_type=ContentFile).data
        if result.type != "file":
            raise GitHubAgentError("path is not a regular file")
        if result.encoding != "base64":
            raise GitHubAgentError("GitHub did not return base64 file content")
        return RepositoryBinaryFile(
            repository=repository,
            path=result.path,
            sha=result.sha,
            size=result.size,
            content_base64=result.content.replace("\n", ""),
        )

    def put_file(
        self,
        repository: str,
        path: str,
        content: str,
        message: str,
        branch: str,
    ) -> RepositoryContentWrite:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        encoded = base64.b64encode(content.encode("utf-8")).decode("ascii")
        return self._write_content(repository, path, encoded, message, branch)

    def put_binary_file(
        self,
        repository: str,
        path: str,
        content_base64: str,
        message: str,
        branch: str,
    ) -> RepositoryContentWrite:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        try:
            base64.b64decode(content_base64, validate=True)
        except ValueError as exc:
            raise GitHubAgentError("content_base64 is not valid base64") from exc
        return self._write_content(repository, path, content_base64, message, branch)

    def delete_file(
        self,
        repository: str,
        path: str,
        message: str,
        branch: str,
    ) -> RepositoryContentDelete:
        repository = self._assert_allowed(repository)
        branch = self._assert_mutable_branch(branch)
        endpoint = f"/repos/{repository}/contents/{self._path(path)}"
        current = self._repo_model(
            repository,
            "GET",
            endpoint + "?ref=" + self._quote(branch),
            response_type=RepositoryFileIdentity,
        ).data
        if current.type != "file":
            raise GitHubAgentError("path is not a regular file")
        result = self._repo_model(
            repository,
            "DELETE",
            endpoint,
            response_type=ContentMutationResult,
            payload=ContentDelete(message=message, branch=branch, sha=current.sha),
        ).data
        return RepositoryContentDelete(
            repository=repository, branch=branch, path=path, commit_sha=result.commit.sha
        )

    def search_code(
        self,
        repository: str,
        query: str,
        per_page: int = 30,
        page: int = 1,
    ) -> RepositoryCodeSearch:
        repository = self._assert_allowed(repository)
        result = self._repo_model(
            repository,
            "GET",
            "/search/code",
            response_type=CodeSearchResult,
            query=CodeSearchQuery(
                q=f"{query} repo:{repository}",
                per_page=max(1, min(per_page, 100)),
                page=max(1, page),
            ),
        ).data
        return RepositoryCodeSearch(
            repository=repository, total_count=result.total_count, items=result.items, page=page
        )

    def _write_content(
        self,
        repository: str,
        path: str,
        content_base64: str,
        message: str,
        branch: str,
    ) -> RepositoryContentWrite:
        endpoint = f"/repos/{repository}/contents/{self._path(path)}"
        current = self._repo_inspect_model(
            repository,
            "GET",
            endpoint + "?ref=" + self._quote(branch),
            response_type=RepositoryFileIdentity,
            unavailable_statuses={404},
        )
        if current is not None and current.type != "file":
            raise GitHubAgentError("existing path is not a regular file")
        response = self._repo_model(
            repository,
            "PUT",
            endpoint,
            response_type=ContentMutationResult,
            payload=ContentWrite(
                message=message,
                content=content_base64,
                branch=branch,
                sha=current.sha if current is not None else None,
            ),
        )
        saved = response.data.content
        if saved is None:
            raise GitHubAgentError("GitHub did not return saved content identity")
        return RepositoryContentWrite(
            status=response.status,
            operation="update" if current is not None else "create",
            repository=repository,
            branch=branch,
            path=path,
            commit_sha=response.data.commit.sha,
            content_sha=saved.sha,
        )
