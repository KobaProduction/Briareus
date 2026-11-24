from __future__ import annotations

import base64
import urllib.parse
from pathlib import Path

from briareus_git.files import FileEncoding, content_fields, encode_content
from briareus_git.local_transport import (
    LocalGitConfig,
    authorize_checkout,
    git_output,
    local_git_path,
    push_checkout,
)
from briareus_git.repository_checkout import RepositoryDestinationError, checkout_repository
from briareus_json_values import JsonObject, json_object

from .api import GitLabApiClient
from .errors import GitLabError, GitLabRequestError
from .models import GitLabCommitAction
from .policy import require_mutable_branch

_LOCAL_GIT = LocalGitConfig(
    "GitLab",
    "project",
    "koba-gitlab-credentials",
    "# koba-managed-gitlab-local-git-guard",
    GitLabError,
    GitLabRequestError,
)


class GitLabRepositoryClient(GitLabApiClient):
    def checkout_repository(
        self,
        project: str | int,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> JsonObject:
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        encoded_project = urllib.parse.quote(raw_project, safe="/-._~")
        clone_url = f"{self.profile.base_url.rstrip('/')}/{encoded_project}.git"

        auth_header = ""
        if not self.anonymous_only:
            token = self.profile.token()
            if self.profile.auth_type == "private_token":
                encoded = base64.b64encode(f"oauth2:{token}".encode()).decode("ascii")
                auth_header = f"Authorization: Basic {encoded}"
            elif self.profile.auth_type == "bearer":
                auth_header = f"Authorization: Bearer {token}"
            else:
                encoded = base64.b64encode(f"gitlab-ci-token:{token}".encode()).decode("ascii")
                auth_header = f"Authorization: Basic {encoded}"

        try:
            result = checkout_repository(
                clone_url,
                destination,
                workspace_root=self.workspace_root,
                mode=mode,
                ref=ref,
                overwrite=overwrite,
                auth_scope=self.profile.base_url.rstrip("/") + "/",
                auth_header=auth_header,
                fallback_without_auth=True,
            )
        except RepositoryDestinationError as exc:
            raise GitLabRequestError(str(exc)) from exc
        result["project"] = raw_project
        result["profile_id"] = self.profile.profile_id
        if result["git_metadata"]:
            result["local_git_hint"] = (
                "For authorize_local_git and push_local_git, pass "
                f"destination={result['path']!r} exactly; it is relative to "
                "SERVER_MOUNT_PATH, never an absolute terminal cwd."
            )
        return result

    def _local_git_path(self, destination: str) -> Path:
        return local_git_path(self.workspace_root, destination, _LOCAL_GIT)

    @staticmethod
    def _git_output(target: Path, *args: str) -> str:
        return git_output(target, *args, config=_LOCAL_GIT)

    def _git_optional_output(self, target: Path, *args: str) -> str:
        return git_output(target, *args, config=_LOCAL_GIT, optional=True)

    def _expected_remote(self, project: str) -> str:
        encoded_project = urllib.parse.quote(project.strip().strip("/"), safe="/-._~")
        return f"{self.profile.base_url.rstrip('/')}/{encoded_project}.git"

    def _git_signature(self) -> dict[str, str]:
        user = self.request("GET", "/user").data
        if not isinstance(user, dict):
            raise GitLabError("unexpected GitLab /user response")
        username = str(user.get("username") or "").strip()
        name = str(user.get("name") or username).strip()
        email = str(
            user.get("commit_email")
            or user.get("email")
            or user.get("public_email")
            or (f"{username}@users.noreply.gitlab.com" if username else "")
        ).strip()
        if not name or not email:
            raise GitLabError("unable to resolve Git identity from GitLab /user")
        return {"name": name, "email": email}

    def _credential_url(self, project: str) -> str:
        parsed = urllib.parse.urlsplit(self.profile.base_url)
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        token = urllib.parse.quote(self.profile.token(), safe="")
        project_path = urllib.parse.quote(project.strip().strip("/"), safe="/-._~")
        base_path = parsed.path.rstrip("/")
        path = f"{base_path}/{project_path}.git"
        netloc = f"{urllib.parse.quote(username, safe='')}:{token}@{parsed.netloc}"
        return urllib.parse.urlunsplit((parsed.scheme, netloc, path, "", ""))

    def authorize_local_git(
        self,
        project: str | int,
        destination: str,
        *,
        remote: str = "origin",
    ) -> JsonObject:
        if self.anonymous_only:
            raise GitLabError(
                "local Git write authorization requires an authenticated GitLab account"
            )
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        expected = self._expected_remote(raw_project)
        return authorize_checkout(
            self,
            _LOCAL_GIT,
            raw_project,
            destination,
            account_id=self.profile.profile_id,
            remote=remote,
            expected=expected,
            accepted=frozenset({expected.removesuffix(".git")}),
            signature=self._git_signature,
            credential_url=lambda: self._credential_url(raw_project),
        )

    def push_local_git(
        self,
        project: str | int,
        destination: str,
        *,
        branch: str = "",
        remote: str = "origin",
        set_upstream: bool = True,
        expected_remote_sha: str = "",
    ) -> JsonObject:
        if self.anonymous_only:
            raise GitLabError("local Git push requires an authenticated GitLab account")
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        result = push_checkout(
            self,
            _LOCAL_GIT,
            raw_project,
            destination,
            account_id=self.profile.profile_id,
            branch=branch,
            remote=remote,
            set_upstream=set_upstream,
            expected=self._expected_remote(raw_project),
            branch_guard=lambda name: require_mutable_branch(name, self.protected_branches),
            expected_remote_sha=expected_remote_sha,
        )
        expected_sha = expected_remote_sha.strip().casefold()
        result.update(
            {"force_with_lease": bool(expected_sha), "expected_remote_sha": expected_sha or None}
        )
        return result

    def get_file(
        self,
        project: str | int,
        path: str,
        ref: str | None = "main",
        encoding: FileEncoding = "utf-8",
    ) -> JsonObject:
        ref = ref or "HEAD"
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": ref},
        )
        data = response.data
        if not isinstance(data, dict):
            raise GitLabError("unexpected GitLab repository file response")
        provider_encoding = str(data.get("encoding", ""))
        content = str(data.get("content", ""))
        if provider_encoding != "base64":
            raise GitLabError(f"unsupported GitLab repository file encoding: {provider_encoding}")
        if encoding == "base64":
            # GitLab's metadata endpoint can transcode non-UTF-8 text; raw is exact.
            commit_id = data.get("commit_id")
            if not isinstance(commit_id, str) or not commit_id:
                raise GitLabError("GitLab file metadata has no commit ID for a pinned raw read")
            raw = self.request_bytes(
                f"/projects/{selector}/repository/files/{file_path}/raw",
                query={"ref": commit_id},
            )
            if isinstance(data.get("size"), int) and len(raw) != data["size"]:
                raise GitLabError("GitLab raw file size does not match pinned metadata")
        else:
            raw = base64.b64decode(content)
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": data.get("file_path", path),
            "ref": ref,
            "blob_id": data.get("blob_id"),
            "commit_id": data.get("commit_id"),
            "last_commit_id": data.get("last_commit_id"),
            "size": data.get("size"),
            **content_fields(raw, encoding),
        }

    def list_tree(
        self,
        project: str | int,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/tree",
            query={
                "path": path or None,
                "ref": ref,
                "recursive": recursive,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab repository tree response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "items": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def search_code(
        self,
        project: str | int,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        query: JsonObject = {
            "scope": "blobs",
            "search": search,
            "page": page,
            "per_page": per_page,
        }
        if ref:
            query["ref"] = ref
        response = self.request("GET", f"/projects/{selector}/search", query=query)
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab code search response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "results": response.data,
            "page": page,
            "per_page": per_page,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def list_commits(
        self,
        project: str | int,
        ref: str = "",
        path: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/commits",
            query={
                "ref_name": ref or None,
                "path": path or None,
                "page": page,
                "per_page": per_page,
            },
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab commit list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "commits": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def get_commit(
        self,
        project: str | int,
        sha: str,
    ) -> JsonObject:
        selector = self.project_selector(project)
        commit = self.request(
            "GET",
            f"/projects/{selector}/repository/commits/{urllib.parse.quote(sha, safe='')}",
        ).data
        diff = self.request(
            "GET",
            f"/projects/{selector}/repository/commits/{urllib.parse.quote(sha, safe='')}/diff",
        ).data
        if not isinstance(diff, list):
            raise GitLabError("unexpected GitLab commit diff response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "commit": commit,
            "diff": diff,
        }

    def put_file(
        self,
        project: str | int,
        path: str,
        content: str,
        message: str,
        branch: str,
        encoding: FileEncoding = "utf-8",
        *,
        last_commit_id: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        if encoding == "base64":
            try:
                encode_content(content, encoding)
            except ValueError as exc:
                raise GitLabRequestError("content is not valid base64") from exc
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        existing = self.request(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query={"ref": branch},
            allowed_errors={404},
        )
        method = "POST" if existing.status == 404 else "PUT"
        payload: JsonObject = {
            "branch": branch,
            "content": content,
            "commit_message": message,
        }
        if encoding == "base64":
            payload["encoding"] = "base64"
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            method,
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "operation": "create" if method == "POST" else "update",
            "result": response.data,
        }

    def delete_file(
        self,
        project: str | int,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        payload: JsonObject = {
            "branch": branch,
            "commit_message": commit_message,
        }
        if last_commit_id:
            payload["last_commit_id"] = last_commit_id
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "path": path,
            "branch": branch,
            "result": response.data,
        }

    def commit_actions(
        self,
        project: str | int,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        if not actions:
            raise GitLabError("actions must not be empty")
        clean_actions = [action.to_json() for action in actions]
        selector = self.project_selector(project)
        payload = json_object(
            {
                "branch": branch,
                "commit_message": commit_message,
                "actions": clean_actions,
            },
            context="GitLab commit payload",
        )
        if start_branch:
            payload["start_branch"] = start_branch
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/commits",
            payload=payload,
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "commit": response.data,
        }

    def list_branches(
        self,
        project: str | int,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/branches",
            query={"search": search or None, "page": page, "per_page": per_page},
        )
        if not isinstance(response.data, list):
            raise GitLabError("unexpected GitLab branch list response")
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branches": response.data,
            "next_page": response.headers.get("X-Next-Page", ""),
        }

    def create_branch(
        self,
        project: str | int,
        branch: str,
        ref: str,
    ) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        response = self.request(
            "POST",
            f"/projects/{selector}/repository/branches",
            query={"branch": branch, "ref": ref},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": response.data,
        }

    def delete_branch(self, project: str | int, branch: str) -> JsonObject:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        branch_q = urllib.parse.quote(branch, safe="")
        response = self.request(
            "DELETE",
            f"/projects/{selector}/repository/branches/{branch_q}",
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "branch": branch,
            "status": response.status,
            "deleted": True,
        }

    def compare(
        self,
        project: str | int,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> JsonObject:
        selector = self.project_selector(project)
        response = self.request(
            "GET",
            f"/projects/{selector}/repository/compare",
            query={"from": from_ref, "to": to_ref, "straight": straight},
        )
        return {
            "profile_id": self.profile.profile_id,
            "project": str(project),
            "comparison": response.data,
        }
