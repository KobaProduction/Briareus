"""Node Git transport: credentials live only in one authorized child process.

Never install a credential helper or execute project hooks. The original
provider HTTP clients and branch policies remain authoritative.
"""
from __future__ import annotations
import base64
import os
import re
import subprocess
import shutil
import json
import hashlib
from contextlib import contextmanager
from uuid import uuid4
from pathlib import Path
from modules.github.github_identity import GitHubPrettyIdentityClient
from modules.gitlab.gitlab_client import GitLabClient
from modules.gitlab.policy import require_mutable_branch
from common.http_transport import PooledHttpTransport
from common.repository_checkout import resolve_workspace_destination
from .node_proxy import provider_connection


def _git(target, *arguments, auth_scope="", auth_header=""):
    env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": "/home/hand",
           "GIT_TERMINAL_PROMPT": "0", "GIT_CONFIG_NOSYSTEM": "1",
           "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null",
           "GIT_ALLOW_PROTOCOL": "https", "GIT_LITERAL_PATHSPECS": "1"}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY",
                "http_proxy", "https_proxy", "all_proxy", "no_proxy"):
        if key in os.environ:
            env[key] = os.environ[key]
    config = [("credential.helper", ""), ("core.hooksPath", "/dev/null"),
              ("core.fsmonitor", "false"), ("protocol.file.allow", "never"),
              ("protocol.ext.allow", "never"), ("http.followRedirects", "false")]
    if auth_header:
        config += [("http." + auth_scope + ".extraHeader", auth_header)]
    env["GIT_CONFIG_COUNT"] = str(len(config))
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    try:
        result = subprocess.run(["git", "-C", str(target), *arguments], env=env,
            capture_output=True, timeout=json.loads(os.environ.get("BRIAREUS_RUNTIME_POLICY", "{}")).get("execution_timeout_seconds"), check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError("NODE_GIT_OPERATION_UNAVAILABLE") from None
    if result.returncode:
        # Provider stderr may contain URLs, headers or an account token.
        raise ValueError("NODE_GIT_OPERATION_FAILED")
    if len(result.stdout) > 262144:
        raise ValueError("NODE_GIT_OUTPUT_LIMIT")
    return result.stdout.decode("utf-8", "replace").strip()


def _target(client, destination, expected, remote):
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", remote):
        raise ValueError("Explicit safe Git remote required")
    target = client._local_git_path(destination)
    if (target / ".git").is_symlink() or not ((target / ".git").is_dir() or (target / ".git").is_file()):
        raise ValueError("Project-local Git directory/worktree required")
    common = Path(_git(target, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
    if not common.is_relative_to(client.workspace_root.resolve()):
        raise ValueError("Git metadata must remain inside current project")
    actual = _git(target, "remote", "get-url", remote)
    if actual.removesuffix(".git") != expected.removesuffix(".git"):
        raise ValueError("Checkout remote does not match approved repository")
    return target


def _authorize(client, repository, destination, remote, expected):
    target = _target(client, destination, expected, remote)
    return {"authorized": True, "repository": str(repository),
            "workspace": target.relative_to(client.workspace_root.resolve()).as_posix(),
            "remote": remote, "remote_url": expected,
            "branch": _git(target, "branch", "--show-current"),
            "credential_storage": "none", "push_mode": "authorized_mcp_call",
            "requires_current_permission_per_push": True}


def _push(client, repository, destination, remote, expected, branch, set_upstream,
          auth_scope, auth_header, expected_remote_sha=""):
    target = _target(client, destination, expected, remote)
    selected = branch.strip() or _git(target, "branch", "--show-current")
    selected = require_mutable_branch(selected, client.protected_branches)
    # Separate ref validation prevents option/refspec injection as well.
    _git(target, "check-ref-format", "refs/heads/" + selected)
    arguments = ["push", "--porcelain"]
    if set_upstream:
        arguments.append("--set-upstream")
    if expected_remote_sha:
        if not re.fullmatch(r"[a-fA-F0-9]{40}", expected_remote_sha):
            raise ValueError("Expected remote SHA must be hexadecimal")
        arguments.append(f"--force-with-lease=refs/heads/{selected}:{expected_remote_sha}")
    arguments += ["--", expected, "HEAD:refs/heads/" + selected]
    _git(target, *arguments, auth_scope=auth_scope, auth_header=auth_header)
    return {"pushed": True, "repository": str(repository),
            "workspace": target.relative_to(client.workspace_root.resolve()).as_posix(),
            "remote": remote, "branch": selected,
            "head": _git(target, "rev-parse", "HEAD"), "credential_storage": "none"}


def _canonical(root, clone_url):
    digest = hashlib.sha256(clone_url.removesuffix(".git").casefold().encode()).hexdigest()
    directory = root / ".briareus-git" / "repositories"
    directory.mkdir(parents=True, exist_ok=True)
    if not directory.resolve().is_relative_to(root) or any(p.is_symlink() for p in (root / ".briareus-git", directory)):
        raise ValueError("Project-local canonical repository required")
    return directory / (digest + ".git")


@contextmanager
def _repository_lock(canonical):
    import fcntl
    lock = canonical.with_suffix(".lock")
    descriptor = os.open(lock, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def _checkout(client, repository, destination, clone_url, auth_scope, auth_header,
              *, mode="snapshot", ref="", overwrite=False, branch=""):
    if mode not in {"git", "snapshot"}:
        raise ValueError("Supported checkout mode required")
    root = client.workspace_root.resolve()
    target = resolve_workspace_destination(root, destination)
    if target.is_relative_to(root / ".briareus-git"):
        raise ValueError("Canonical repository storage is reserved; select an agent worktree path")
    canonical = _canonical(root, clone_url)
    with _repository_lock(canonical):
        if canonical.is_symlink():
            raise ValueError("Canonical repository symlink rejected")
        if target.exists():
            # Never destroy data through checkout overwrite. Existing exact worktrees are reused.
            if mode == "git" and (target / ".git").is_file():
                _target(client, destination, clone_url, "origin")
                actual = Path(_git(target, "rev-parse", "--path-format=absolute", "--git-common-dir")).resolve()
                if actual == canonical.resolve():
                    return {"path": target.relative_to(root).as_posix(), "mode": mode,
                            "branch": _git(target, "branch", "--show-current"), "reused": True,
                            "canonical_repository": canonical.relative_to(root).as_posix(),
                            "git_metadata": True, "credential_storage": "none"}
            raise ValueError("Destination exists; preserve it or choose a new worktree path")
        if not canonical.exists():
            temporary = canonical.parent / (".clone-" + uuid4().hex)
            try:
                _git(root, "clone", "--bare", "--template=", "--", clone_url, str(temporary),
                     auth_scope=auth_scope, auth_header=auth_header)
                os.replace(temporary, canonical)
            finally:
                if temporary.exists():
                    shutil.rmtree(temporary)
        elif _git(canonical, "remote", "get-url", "origin").removesuffix(".git") != clone_url.removesuffix(".git"):
            raise ValueError("Canonical remote mismatch")
        # Refresh remote-tracking refs without overwriting any local agent branch.
        _git(canonical, "fetch", "--no-tags", "origin", "+refs/heads/*:refs/remotes/origin/*",
             auth_scope=auth_scope, auth_header=auth_header)
        selected = ref.strip()
        if not selected:
            advertised=_git(canonical,"ls-remote","--symref","origin","HEAD",auth_scope=auth_scope,auth_header=auth_header)
            default=next((line.split()[1] for line in advertised.splitlines() if line.startswith("ref: ") and line.endswith("\tHEAD")),None)
            if not default or not default.startswith("refs/heads/"):
                raise ValueError("Remote default branch unavailable; select an explicit branch")
            selected=default[len("refs/heads/"):]

        if selected != "HEAD":
            _git(canonical, "check-ref-format", "refs/heads/" + selected)
            selected = "refs/remotes/origin/" + selected
        branch = branch.strip() or "agents/" + uuid4().hex
        require_mutable_branch(branch, client.protected_branches)
        _git(canonical, "check-ref-format", "refs/heads/" + branch)
        target.parent.mkdir(parents=True, exist_ok=True)
        _git(canonical, "worktree", "add", "-b", branch, "--", str(target), selected)
        if mode == "snapshot":
            # Export a copy, then remove the temporary linked worktree using Git itself.
            export = target.parent / (".snapshot-" + uuid4().hex)
            try:
                shutil.copytree(target, export, ignore=shutil.ignore_patterns(".git"))
                _git(canonical, "worktree", "remove", "--", str(target))
                _git(canonical, "branch", "-D", "--", branch)
                os.replace(export, target)
            finally:
                if export.exists():
                    shutil.rmtree(export)
        return {"path": target.relative_to(root).as_posix(), "mode": mode, "ref": ref,
                "branch": branch if mode == "git" else None, "git_metadata": mode == "git",
                "canonical_repository": canonical.relative_to(root).as_posix(),
                "reused": False, "credential_storage": "none"}


def _cleanup_merged(client, repository, branch, expected_head):
    root = client.workspace_root.resolve()
    canonical = _canonical(root, client._expected_remote(str(repository)))
    result = {"removed_worktrees": [], "preserved_worktrees": [], "branch_deleted": False}
    if not canonical.exists():
        return result
    try:
        with _repository_lock(canonical):
            listing = _git(canonical, "worktree", "list", "--porcelain", "-z")
            for block in listing.split("\0\0"):
                fields = dict(line.split(" ", 1) for line in block.split("\0") if " " in line)
                if fields.get("branch") != "refs/heads/" + branch:
                    continue
                path = Path(fields.get("worktree", "")).resolve()
                if path == root or not path.is_relative_to(root) or path.is_relative_to(root / ".briareus-git"):
                    continue
                relative = path.relative_to(root).as_posix()
                if fields.get("HEAD") != expected_head or _git(path, "status", "--porcelain=v1", "--untracked-files=all", "--ignored"):
                    result["preserved_worktrees"].append(relative)
                    continue
                # No --force: Git independently refuses dirty/locked worktrees.
                try:
                    _git(canonical, "worktree", "remove", "--", str(path))
                    result["removed_worktrees"].append(relative)
                except ValueError:
                    result["preserved_worktrees"].append(relative)
            if not result["preserved_worktrees"]:
                try:
                    current = _git(canonical, "rev-parse", "refs/heads/" + branch)
                    if current == expected_head:
                        _git(canonical, "update-ref", "-d", "refs/heads/" + branch, expected_head)
                        result["branch_deleted"] = True
                except ValueError:
                    pass
    except (ValueError, OSError):
        result["status"] = "cleanup_incomplete"
    return result


class NodeGitHubClient(GitHubPrettyIdentityClient):
    def __post_init__(self):
        self._transport = PooledHttpTransport(
            lambda: provider_connection("https://api.github.com"),
            max_connections=self.max_connections, acquire_timeout=30,
            span_name="provider.github.http", provider="github")

    def checkout_repository(self, repository, destination, *, mode="snapshot", ref="", overwrite=False):
        repository = self._assert_allowed(repository)
        token = self.token
        if not token:
            try:
                token = self._installation_token(repository)
            except Exception as exc:
                if "is not installed for GitHub App" not in str(exc):
                    raise
                status, metadata = self._request("GET", "https://api.github.com/repos/" + repository)
                if status != 200 or not isinstance(metadata, dict) or metadata.get("private") is not False:
                    raise ValueError("Public repository visibility required") from exc
        return _checkout(self, repository, destination, self._expected_remote(repository),
            "https://github.com/", self._git_authorization_header(token), mode=mode, ref=ref, overwrite=overwrite)

    def _delete_source_branch_cas(self, repository, branch, expected_head):
        repository = self._assert_allowed(repository)
        branch = require_mutable_branch(branch, self.protected_branches)
        if not re.fullmatch(r"[a-fA-F0-9]{40}", expected_head):
            raise ValueError("Exact expected branch SHA required")
        root = self.workspace_root.resolve()
        cache = _canonical(root, self._expected_remote(repository)).parent
        temporary = cache / (".delete-" + uuid4().hex)
        token = self.token or self._installation_token(repository)
        if not token:
            raise ValueError("Current selected account credential required")
        try:
            _git(root, "init", "--bare", "--template=", str(temporary))
            _git(temporary, "check-ref-format", "refs/heads/" + branch)
            _git(temporary, "push", "--porcelain",
                 "--force-with-lease=refs/heads/" + branch + ":" + expected_head,
                 "--", self._expected_remote(repository), ":refs/heads/" + branch,
                 auth_scope="https://github.com/", auth_header=self._git_authorization_header(token))
        finally:
            if temporary.exists() and temporary.resolve().is_relative_to(cache.resolve()):
                shutil.rmtree(temporary)

    def create_worktree(self, repository, destination, branch, ref=""):
        repository = self._assert_allowed(repository)
        token = self.token or self._installation_token(repository)
        return _checkout(self, repository, destination, self._expected_remote(repository),
            "https://github.com/", self._git_authorization_header(token), mode="git", ref=ref, branch=branch)

    def _cleanup_merged_worktrees(self, repository, branch, expected_head):
        return _cleanup_merged(self, repository, branch, expected_head)

    def authorize_local_git(self, repository, destination, *, remote="origin"):
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise ValueError("Authenticated selected account required")
        return _authorize(self, repository, destination, remote, self._expected_remote(repository))

    def push_local_git(self, repository, destination, *, branch="", remote="origin", set_upstream=True):
        repository = self._assert_allowed(repository)
        if self.public_only:
            raise ValueError("Authenticated selected account required")
        token = self.token or self._installation_token(repository)
        encoded = base64.b64encode(("x-access-token:" + token).encode()).decode("ascii")
        return _push(self, repository, destination, remote, self._expected_remote(repository),
                     branch, set_upstream, "https://github.com/", "Authorization: Basic " + encoded)


class NodeGitLabClient(GitLabClient):
    def _new_connection(self):
        return provider_connection(self.profile.base_url, verify_tls=self.profile.verify_tls,
            ca_cert_pem=self.profile.ca_cert_pem, timeout=30)

    def checkout_repository(self, project, destination, *, mode="snapshot", ref="", overwrite=False):
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        encoded = base64.b64encode((username + ":" + self.profile.token()).encode()).decode("ascii")
        return _checkout(self, project, destination, self._expected_remote(str(project)),
            self.profile.base_url.rstrip("/") + "/", "Authorization: Basic " + encoded,
            mode=mode, ref=ref, overwrite=overwrite)

    def create_worktree(self, project, destination, branch, ref=""):
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        encoded = base64.b64encode((username + ":" + self.profile.token()).encode()).decode("ascii")
        return _checkout(self, project, destination, self._expected_remote(str(project)),
            self.profile.base_url.rstrip("/") + "/", "Authorization: Basic " + encoded,
            mode="git", ref=ref, branch=branch)

    def _cleanup_merged_worktrees(self, repository, branch, expected_head):
        return _cleanup_merged(self, repository, branch, expected_head)

    def authorize_local_git(self, project, destination, *, remote="origin"):
        if self.anonymous_only:
            raise ValueError("Authenticated selected account required")
        return _authorize(self, project, destination, remote, self._expected_remote(str(project)))

    def push_local_git(self, project, destination, *, branch="", remote="origin",
                       set_upstream=True, expected_remote_sha=""):
        if self.anonymous_only:
            raise ValueError("Authenticated selected account required")
        username = "gitlab-ci-token" if self.profile.auth_type == "job_token" else "oauth2"
        encoded = base64.b64encode((username + ":" + self.profile.token()).encode()).decode("ascii")
        return _push(self, project, destination, remote, self._expected_remote(str(project)),
                     branch, set_upstream, self.profile.base_url.rstrip("/") + "/",
                     "Authorization: Basic " + encoded, expected_remote_sha)
