from __future__ import annotations

import base64
import urllib.parse
from pathlib import Path
from typing import Never

from service_runtime.repository_checkout import checkout_repository
from source_control.providers.git_process import git_output

from .api import GitLabApiClient
from .errors import GitLabError
from .infrastructure.schemas.identity import AuthenticatedGitLabUser
from .infrastructure.schemas.repository import (
    BranchCreate,
    BranchQuery,
    BranchRecords,
    CodeMatches,
    CodeSearchQuery,
    CommitActions,
    CommitQuery,
    CommitRecords,
    CompareQuery,
    Comparison,
    DiffRecords,
    FileDelete,
    FileMutation,
    FileWrite,
    GitLabBranch,
    GitLabCommit,
    GitLabFile,
    RefQuery,
    TreeQuery,
    TreeRecords,
)
from .local_git_views import GitLabCheckout, GitLabGitAuthorization, GitLabGitPush
from .models import GitLabCommitAction
from .policy import require_mutable_branch
from .repository_views import (
    GitSignature,
    RepositoryActions,
    RepositoryBranchCreated,
    RepositoryBranchDeleted,
    RepositoryBranches,
    RepositoryCommit,
    RepositoryCommits,
    RepositoryComparison,
    RepositoryFile,
    RepositoryFileDelete,
    RepositoryFileWrite,
    RepositorySearch,
    RepositoryTree,
)


class GitLabRepositoryOperations[
    CheckoutAlternative = Never,
    AuthorizationAlternative = Never,
    PushAlternative = Never,
](GitLabApiClient):
    def checkout_repository(
        self,
        project: str | int,
        destination: str,
        *,
        mode: str = "snapshot",
        ref: str = "",
        overwrite: bool = False,
    ) -> GitLabCheckout | CheckoutAlternative:
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
        return GitLabCheckout(
            path=result.path,
            resolved_path=result.resolved_path,
            mode=result.mode,
            ref=result.ref,
            git_metadata=result.git_metadata,
            auth_mode=result.auth_mode,
            project=raw_project,
            profile_id=self.profile.profile_id,
        )

    def _local_git_path(self, destination: str) -> Path:
        root = self.workspace_root.resolve(strict=False)
        raw = destination.strip().replace("\\", "/").lstrip("/")
        if not raw:
            raise GitLabError("workspace destination is required")
        target = (root / raw).resolve(strict=False)
        if target == root or not target.is_relative_to(root):
            raise GitLabError("workspace destination escapes workspace root")
        if not (target / ".git").exists():
            raise GitLabError(f"workspace is not a Git checkout: {destination}")
        return target

    @staticmethod
    def _git_output(target: Path, *args: str) -> str:
        return git_output(target, *args, timeout_seconds=120, error_type=GitLabError)

    def _git_optional_output(self, target: Path, *args: str) -> str:
        return git_output(
            target, *args, timeout_seconds=30, error_type=GitLabError, allow_missing=True
        )

    def _expected_remote(self, project: str) -> str:
        encoded_project = urllib.parse.quote(project.strip().strip("/"), safe="/-._~")
        return f"{self.profile.base_url.rstrip('/')}/{encoded_project}.git"

    def _git_signature(self) -> GitSignature:
        user = self.request_model("GET", "/user", response_type=AuthenticatedGitLabUser).data
        username = user.username.strip()
        name = (user.name or username).strip()
        email = str(
            user.commit_email
            or user.email
            or user.public_email
            or (f"{username}@users.noreply.gitlab.com" if username else "")
        ).strip()
        if not name or not email:
            raise GitLabError("unable to resolve Git identity from GitLab /user")
        return GitSignature(name=name, email=email)

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
    ) -> GitLabGitAuthorization | AuthorizationAlternative:
        if self.anonymous_only:
            raise GitLabError(
                "local Git write authorization requires an authenticated GitLab account"
            )
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        expected = self._expected_remote(raw_project)
        current = self._git_output(target, "remote", "get-url", remote)
        if current.removesuffix(".git") != expected.removesuffix(".git"):
            raise GitLabError(
                f"workspace remote {remote!r} does not match project {raw_project!r}: {current}"
            )

        git_dir = target / ".git"
        credential_file = git_dir / "koba-gitlab-credentials"
        hook = git_dir / "hooks" / "pre-push"
        hook.parent.mkdir(parents=True, exist_ok=True)
        marker = "# koba-managed-gitlab-local-git-guard"
        if hook.exists():
            existing = hook.read_text(encoding="utf-8", errors="replace")
            if marker not in existing:
                raise GitLabError(
                    "existing pre-push hook is not managed by Koba; refusing to overwrite it"
                )

        credential_file.write_text(self._credential_url(raw_project) + "\n", encoding="utf-8")
        credential_file.chmod(0o600)
        reserved = " ".join(sorted(self.protected_branches))
        hook.write_text(
            "#!/bin/sh\n"
            f"{marker}\n"
            "set -eu\n"
            f'reserved=" {reserved} "\n'
            "while read local_ref local_oid remote_ref remote_oid; do\n"
            '  case "$remote_ref" in\n'
            "    refs/heads/*) branch=${remote_ref#refs/heads/} ;;\n"
            "    *) continue ;;\n"
            "  esac\n"
            '  case "$reserved" in\n'
            '    *" $branch "*) echo "push to bridge-reserved branch denied: $branch" >&2; '
            "exit 1 ;;\n"
            "  esac\n"
            "done\n",
            encoding="utf-8",
        )
        hook.chmod(0o700)

        signature = self._git_signature()
        helper = f"store --file={credential_file}"
        self._git_output(target, "config", "--local", "user.name", signature.name)
        self._git_output(target, "config", "--local", "user.email", signature.email)
        self._git_output(target, "config", "--local", f"remote.{remote}.url", expected)
        self._git_output(target, "config", "--local", "credential.helper", helper)
        self._git_output(target, "config", "--local", "credential.useHttpPath", "true")
        self._git_output(target, "config", "--local", "koba.gitlab.project", raw_project)
        self._git_output(
            target,
            "config",
            "--local",
            "koba.gitlab.accountId",
            self.profile.profile_id,
        )
        self._git_output(
            target,
            "config",
            "--local",
            "koba.gitlab.transportAuthorized",
            "true",
        )
        branch = self._git_output(target, "branch", "--show-current")
        return GitLabGitAuthorization(
            authorized=True,
            project=raw_project,
            workspace=target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            remote=remote,
            remote_url=expected,
            branch=branch,
            account_id=self.profile.profile_id,
            credential_storage="git_credential_store",
            credential_file=credential_file.relative_to(target).as_posix(),
            push_mode="ordinary_git",
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
    ) -> GitLabGitPush | PushAlternative:
        if self.anonymous_only:
            raise GitLabError("local Git push requires an authenticated GitLab account")
        raw_project = str(project).strip().strip("/")
        if not raw_project:
            raise GitLabError("project is required")
        target = self._local_git_path(destination)
        remote = remote.strip() or "origin"
        marker_project = self._git_optional_output(
            target, "config", "--local", "--get", "koba.gitlab.project"
        )
        marker_account = self._git_optional_output(
            target, "config", "--local", "--get", "koba.gitlab.accountId"
        )
        marker_enabled = self._git_optional_output(
            target, "config", "--local", "--get", "koba.gitlab.transportAuthorized"
        )
        if (
            marker_project != raw_project
            or marker_account != self.profile.profile_id
            or marker_enabled.casefold() != "true"
        ):
            raise GitLabError(
                "workspace is not authorized for this GitLab account/project; "
                "call authorize_local_git first"
            )

        current_branch = self._git_output(target, "branch", "--show-current")
        push_branch = (branch.strip() or current_branch).strip()
        if not push_branch:
            raise GitLabError("cannot push a detached HEAD; specify a local branch")
        push_branch = require_mutable_branch(push_branch, self.protected_branches)
        # Only remove our obsolete guard. Preserve all third-party Git hooks.
        if not self.protected_branches:
            guard = target / ".git" / "hooks" / "pre-push"
            if guard.is_file() and "# koba-managed-gitlab-local-git-guard" in guard.read_text(
                encoding="utf-8", errors="replace"
            ):
                guard.unlink()

        expected_sha = expected_remote_sha.strip().casefold()
        if expected_sha and (
            len(expected_sha) != 40 or any(ch not in "0123456789abcdef" for ch in expected_sha)
        ):
            raise GitLabError("expected_remote_sha must be a 40-character hexadecimal commit SHA")

        args = ["push", "--porcelain"]
        if set_upstream:
            args.append("--set-upstream")
        if expected_sha:
            args.append(f"--force-with-lease=refs/heads/{push_branch}:{expected_sha}")
        args += [remote, f"HEAD:refs/heads/{push_branch}"]
        output = self._git_output(target, *args)
        head = self._git_output(target, "rev-parse", "HEAD")
        return GitLabGitPush(
            pushed=True,
            project=raw_project,
            workspace=target.relative_to(self.workspace_root.resolve(strict=False)).as_posix(),
            remote=remote,
            branch=push_branch,
            head=head,
            account_id=self.profile.profile_id,
            force_with_lease=bool(expected_sha),
            expected_remote_sha=expected_sha or None,
            git_output=output[-2048:],
        )

    def get_file(self, project: str | int, path: str, ref: str = "main") -> RepositoryFile:
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        response = self.request_model(
            "GET",
            f"/projects/{selector}/repository/files/{file_path}",
            query=RefQuery(ref=ref),
            response_type=GitLabFile,
        )
        data = response.data
        encoding = data.encoding
        content = data.content
        if encoding != "base64":
            raise GitLabError(f"unsupported GitLab repository file encoding: {encoding}")
        decoded = base64.b64decode(content).decode("utf-8", "replace")
        return RepositoryFile(
            profile_id=self.profile.profile_id,
            project=str(project),
            path=data.file_path,
            ref=ref,
            blob_id=data.blob_id,
            commit_id=data.commit_id,
            last_commit_id=data.last_commit_id,
            size=data.size,
            content=decoded,
        )

    def list_tree(
        self,
        project: str | int,
        path: str = "",
        ref: str = "main",
        recursive: bool = False,
        page: int = 1,
        per_page: int = 100,
    ) -> RepositoryTree:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/repository/tree",
            query=TreeQuery(
                path=path or None, ref=ref, recursive=recursive, page=page, per_page=per_page
            ),
            response_type=TreeRecords,
        )
        return RepositoryTree(
            profile_id=self.profile.profile_id,
            project=str(project),
            items=response.data.root,
            page=page,
            per_page=per_page,
            next_page=response.pagination.next_page,
        )

    def search_code(
        self,
        project: str | int,
        search: str,
        ref: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> RepositorySearch:
        selector = self.project_selector(project)
        query = CodeSearchQuery(search=search, ref=ref or None, page=page, per_page=per_page)
        response = self.request_model(
            "GET", f"/projects/{selector}/search", query=query, response_type=CodeMatches
        )
        return RepositorySearch(
            profile_id=self.profile.profile_id,
            project=str(project),
            results=response.data.root,
            page=page,
            per_page=per_page,
            next_page=response.pagination.next_page,
        )

    def list_commits(
        self,
        project: str | int,
        ref: str = "",
        path: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> RepositoryCommits:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/repository/commits",
            query=CommitQuery(
                ref_name=ref or None, path=path or None, page=page, per_page=per_page
            ),
            response_type=CommitRecords,
        )
        return RepositoryCommits(
            profile_id=self.profile.profile_id,
            project=str(project),
            commits=response.data.root,
            next_page=response.pagination.next_page,
        )

    def get_commit(
        self,
        project: str | int,
        sha: str,
    ) -> RepositoryCommit:
        selector = self.project_selector(project)
        commit = self.request_model(
            "GET",
            f"/projects/{selector}/repository/commits/{urllib.parse.quote(sha, safe='')}",
            response_type=GitLabCommit,
        ).data
        diff = self.request_model(
            "GET",
            f"/projects/{selector}/repository/commits/{urllib.parse.quote(sha, safe='')}/diff",
            response_type=DiffRecords,
        ).data.root
        return RepositoryCommit(
            profile_id=self.profile.profile_id, project=str(project), commit=commit, diff=diff
        )

    def put_file(
        self,
        project: str | int,
        path: str,
        content: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> RepositoryFileWrite:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        existing = self.inspect_model(
            f"/projects/{selector}/repository/files/{file_path}",
            query=RefQuery(ref=branch),
            response_type=GitLabFile,
            unavailable_statuses={404},
        )
        method = "POST" if existing is None else "PUT"
        payload = FileWrite(
            branch=branch,
            content=content,
            commit_message=commit_message,
            last_commit_id=last_commit_id or None,
        )
        response = self.request_model(
            method,
            f"/projects/{selector}/repository/files/{file_path}",
            payload=payload,
            response_type=FileMutation,
        )
        return RepositoryFileWrite(
            profile_id=self.profile.profile_id,
            project=str(project),
            path=path,
            branch=branch,
            operation="create" if method == "POST" else "update",
            result=response.data,
        )

    def delete_file(
        self,
        project: str | int,
        path: str,
        branch: str,
        commit_message: str,
        last_commit_id: str = "",
    ) -> RepositoryFileDelete:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        file_path = urllib.parse.quote(path.strip("/"), safe="")
        payload = FileDelete(
            branch=branch, commit_message=commit_message, last_commit_id=last_commit_id or None
        )
        self.request_ack(
            "DELETE", f"/projects/{selector}/repository/files/{file_path}", payload=payload
        )
        return RepositoryFileDelete(
            profile_id=self.profile.profile_id,
            project=str(project),
            path=path,
            branch=branch,
            result=None,
        )

    def commit_actions(
        self,
        project: str | int,
        branch: str,
        commit_message: str,
        actions: list[GitLabCommitAction],
        start_branch: str = "",
    ) -> RepositoryActions:
        branch = require_mutable_branch(branch, self.protected_branches)
        if not actions:
            raise GitLabError("actions must not be empty")
        selector = self.project_selector(project)
        payload = CommitActions(
            branch=branch,
            commit_message=commit_message,
            actions=actions,
            start_branch=start_branch or None,
        )
        response = self.request_model(
            "POST",
            f"/projects/{selector}/repository/commits",
            payload=payload,
            response_type=GitLabCommit,
        )
        return RepositoryActions(
            profile_id=self.profile.profile_id,
            project=str(project),
            branch=branch,
            commit=response.data,
        )

    def list_branches(
        self,
        project: str | int,
        search: str = "",
        page: int = 1,
        per_page: int = 100,
    ) -> RepositoryBranches:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/repository/branches",
            query=BranchQuery(search=search or None, page=page, per_page=per_page),
            response_type=BranchRecords,
        )
        return RepositoryBranches(
            profile_id=self.profile.profile_id,
            project=str(project),
            branches=response.data.root,
            next_page=response.pagination.next_page,
        )

    def create_branch(
        self,
        project: str | int,
        branch: str,
        ref: str,
    ) -> RepositoryBranchCreated:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        response = self.request_model(
            "POST",
            f"/projects/{selector}/repository/branches",
            query=BranchCreate(branch=branch, ref=ref),
            response_type=GitLabBranch,
        )
        return RepositoryBranchCreated(
            profile_id=self.profile.profile_id, project=str(project), branch=response.data
        )

    def delete_branch(self, project: str | int, branch: str) -> RepositoryBranchDeleted:
        branch = require_mutable_branch(branch, self.protected_branches)
        selector = self.project_selector(project)
        branch_q = urllib.parse.quote(branch, safe="")
        response = self.request_ack(
            "DELETE",
            f"/projects/{selector}/repository/branches/{branch_q}",
        )
        return RepositoryBranchDeleted(
            profile_id=self.profile.profile_id,
            project=str(project),
            branch=branch,
            status=response.status,
            deleted=True,
        )

    def compare(
        self,
        project: str | int,
        from_ref: str,
        to_ref: str,
        straight: bool = False,
    ) -> RepositoryComparison:
        selector = self.project_selector(project)
        response = self.request_model(
            "GET",
            f"/projects/{selector}/repository/compare",
            query=CompareQuery(from_ref=from_ref, to=to_ref, straight=straight),
            response_type=Comparison,
        )
        return RepositoryComparison(
            profile_id=self.profile.profile_id, project=str(project), comparison=response.data
        )
