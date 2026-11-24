"""Provider-neutral local Git authorization and publication.

The owner supplies identity, credentials, repository permission checks and
native remote rules. This module owns the filesystem and Git command lifecycle.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from briareus_json_values import JsonObject

from .repository_checkout import (
    RepositoryCheckoutError,
    RepositoryDestinationError,
    checkout_destination,
    retryable_git_auth_failure,
)


class LocalGitHost(Protocol):
    workspace_root: Path
    protected_branches: frozenset[str]

    def _local_git_path(self, destination: str) -> Path: ...
    def _git_output(self, target: Path, *args: str) -> str: ...
    def _git_optional_output(self, target: Path, *args: str) -> str: ...
    def authorize_local_git(
        self, repository: str, destination: str, *, remote: str = "origin"
    ) -> JsonObject: ...


@dataclass(frozen=True)
class LocalGitConfig:
    provider: str
    resource_key: str
    credential_filename: str
    hook_marker: str
    error: type[Exception]
    request_error: type[Exception]

    @property
    def config_prefix(self) -> str:
        return f"koba.{self.provider.lower()}."


def local_git_path(root: Path, destination: str, config: LocalGitConfig) -> Path:
    try:
        target = checkout_destination(root.resolve(strict=False), destination)
    except RepositoryDestinationError as exc:
        raise config.request_error(str(exc)) from exc
    except RepositoryCheckoutError as exc:
        raise config.error(str(exc)) from exc
    if not (target / ".git").exists():
        raise config.request_error(
            "destination is not a Git checkout. Use the exact mount-relative "
            "'path' from checkout_repository(mode='git'), not an absolute "
            "terminal cwd or workspace_id."
        )
    return target


def git_output(
    target: Path,
    *args: str,
    config: LocalGitConfig,
    optional: bool = False,
    env: dict[str, str] | None = None,
) -> str:
    environment = os.environ.copy() if env is None else env.copy()
    environment["GIT_TERMINAL_PROMPT"] = "0"
    try:
        result = subprocess.run(
            ["git", "-C", str(target), *args],
            check=False,
            capture_output=True,
            text=True,
            env=environment,
            timeout=30 if optional else 120,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        raise config.error("local Git command failed or timed out") from exc
    detail = (result.stderr or result.stdout).strip()
    if optional and result.returncode == 1 and not detail:
        return ""
    if result.returncode:
        # Avoid returning URL credentials in command diagnostics.
        detail = re.sub(r"(https?://)[^\s/@]+@", r"\1[redacted]@", detail)
        raise config.error(
            f"git command failed with exit code {result.returncode}: {detail[-2048:]}"
        )
    return (result.stdout or result.stderr).strip()


def remote_name(remote: str, config: LocalGitConfig) -> str:
    name = remote.strip() or "origin"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]*", name):
        raise config.request_error("invalid Git remote name")
    return name


def _check_remote(
    host: LocalGitHost, target: Path, remote: str, accepted: frozenset[str], config: LocalGitConfig
) -> None:
    for options in ((), ("--push",)):
        urls = host._git_output(target, "remote", "get-url", *options, "--all", remote).splitlines()
        if len(urls) != 1 or urls[0].removesuffix(".git") not in accepted:
            raise config.error(
                f"workspace remote {remote!r} does not match the selected {config.resource_key}"
            )


def _atomic_write(path: Path, content: str, mode: int) -> None:
    fd, temp = tempfile.mkstemp(prefix=".briareus-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as output:
            output.write(content)
            os.fchmod(output.fileno(), mode)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def _guard_script(marker: str, branches: frozenset[str]) -> str:
    reserved = " " + " ".join(sorted(branch.casefold() for branch in branches)) + " "
    return (
        "#!/bin/sh\n"
        + marker
        + "\nset -eu\n"
        + "reserved="
        + shlex.quote(reserved)
        + "\n"
        + "while read local_ref local_oid remote_ref remote_oid; do\n"
        + '  case "$remote_ref" in\n'
        + "    refs/heads/*) branch=${remote_ref#refs/heads/} ;;\n"
        + "    *) continue ;;\n  esac\n"
        + '  lower=$(printf "%s" "$branch" | LC_ALL=C tr "[:upper:]" "[:lower:]")\n'
        + '  case "$reserved" in\n'
        + '    *" $lower "*) echo "push to reserved branch denied: $branch" >&2; exit 1 ;;\n'
        + "  esac\ndone\n"
    )


def _managed_hook(target: Path, config: LocalGitConfig) -> Path:
    git_dir = target / ".git"
    if not git_dir.is_dir() or git_dir.is_symlink():
        raise config.error("local Git authorization requires a regular .git directory")
    hook = git_dir / "hooks" / "pre-push"
    if hook.parent.is_symlink() or hook.is_symlink():
        raise config.error("refusing a symlinked Git hook path")
    return hook


def _check_hook(host: LocalGitHost, target: Path, config: LocalGitConfig) -> Path:
    hook = _managed_hook(target, config)
    if hook.exists() and config.hook_marker not in hook.read_text(
        encoding="utf-8", errors="replace"
    ):
        raise config.error(
            "existing pre-push hook is not managed by Koba; refusing to overwrite it"
        )
    hooks_path = host._git_optional_output(target, "config", "--get", "core.hooksPath")
    if host.protected_branches and hooks_path:
        # The provider's reserved-branch guard must actually be active.
        effective = (target / hooks_path).resolve()
        if effective != hook.parent.resolve():
            raise config.error("custom core.hooksPath would bypass the reserved-branch guard")
    return hook


def _configure(
    host: LocalGitHost,
    target: Path,
    config: LocalGitConfig,
    repository: str,
    account_id: str,
    remote: str,
    expected: str,
    signature: dict[str, str],
    credential_file: Path,
) -> None:
    prefix = config.config_prefix
    for key, value in (
        ("user.name", signature["name"]),
        ("user.email", signature["email"]),
        (f"remote.{remote}.url", expected),
        ("credential.helper", f"store --file={shlex.quote(str(credential_file))}"),
        ("credential.useHttpPath", "true"),
        (prefix + config.resource_key, repository),
        (prefix + "accountId", account_id),
    ):
        host._git_output(target, "config", "--local", key, value)


def authorize_checkout(
    host: LocalGitHost,
    config: LocalGitConfig,
    repository: str,
    destination: str,
    *,
    account_id: str,
    remote: str,
    expected: str,
    accepted: frozenset[str],
    signature: Callable[[], dict[str, str]],
    credential_url: Callable[[], str],
) -> JsonObject:
    target = host._local_git_path(destination)
    remote = remote_name(remote, config)
    _check_remote(host, target, remote, accepted, config)
    hook = _check_hook(host, target, config)
    push_url = host._git_optional_output(target, "config", "--get", f"remote.{remote}.pushurl")
    if push_url and push_url.removesuffix(".git") != expected.removesuffix(".git"):
        raise config.error("explicit pushurl must match the selected provider HTTPS repository")
    identity = signature()
    credential = credential_url()
    credential_file = target / ".git" / config.credential_filename
    hook.parent.mkdir(parents=True, exist_ok=True)
    # Never follow an existing credential symlink or temporarily publish a
    # world-readable token. Preserve the provider's stable filename.
    host._git_output(
        target, "config", "--local", config.config_prefix + "transportAuthorized", "false"
    )
    _atomic_write(credential_file, credential + "\n", 0o600)
    _atomic_write(hook, _guard_script(config.hook_marker, host.protected_branches), 0o700)
    _configure(
        host, target, config, repository, account_id, remote, expected, identity, credential_file
    )
    _check_remote(host, target, remote, frozenset({expected.removesuffix(".git")}), config)
    host._git_output(
        target, "config", "--local", config.config_prefix + "transportAuthorized", "true"
    )
    return {
        "authorized": True,
        config.resource_key: repository,
        "workspace": target.relative_to(host.workspace_root.resolve(strict=False)).as_posix(),
        "remote": remote,
        "remote_url": expected,
        "branch": host._git_output(target, "branch", "--show-current"),
        "account_id": account_id,
        "credential_storage": "git_credential_store",
        "credential_file": credential_file.relative_to(target).as_posix(),
        "push_mode": "ordinary_git",
    }


def _check_authority(
    host: LocalGitHost, target: Path, config: LocalGitConfig, repository: str, account_id: str
) -> None:
    prefix = config.config_prefix
    values = [
        host._git_optional_output(target, "config", "--local", "--get", prefix + key)
        for key in (config.resource_key, "accountId", "transportAuthorized")
    ]
    if values[:2] != [repository, account_id] or values[2].casefold() != "true":
        raise config.error(
            f"workspace is not authorized for this {config.provider} "
            f"account/{config.resource_key}; "
            "call authorize_local_git first"
        )


def _remove_obsolete_guard(host: LocalGitHost, target: Path, config: LocalGitConfig) -> None:
    guard = target / ".git" / "hooks" / "pre-push"
    if (
        not host.protected_branches
        and guard.is_file()
        and not guard.is_symlink()
        and not guard.parent.is_symlink()
        and not (target / ".git").is_symlink()
        and config.hook_marker in guard.read_text(encoding="utf-8", errors="replace")
    ):
        guard.unlink()


def _push_args(remote: str, branch: str, set_upstream: bool, expected_sha: str) -> list[str]:
    args = ["push", "--porcelain"]
    if set_upstream:
        args.append("--set-upstream")
    if expected_sha:
        args.append(f"--force-with-lease=refs/heads/{branch}:{expected_sha}")
    return [*args, "--", remote, f"HEAD:refs/heads/{branch}"]


def push_checkout(
    host: LocalGitHost,
    config: LocalGitConfig,
    repository: str,
    destination: str,
    *,
    account_id: str,
    branch: str,
    remote: str,
    set_upstream: bool,
    expected: str,
    branch_guard: Callable[[str], str],
    expected_remote_sha: str = "",
) -> JsonObject:
    target = host._local_git_path(destination)
    remote = remote_name(remote, config)
    _check_authority(host, target, config, repository, account_id)
    _check_remote(host, target, remote, frozenset({expected.removesuffix(".git")}), config)
    push_branch = branch.strip() or host._git_output(target, "branch", "--show-current").strip()
    if not push_branch:
        raise config.error("cannot push a detached HEAD; specify a local branch")
    push_branch = branch_guard(push_branch)
    expected_sha = expected_remote_sha.strip().casefold()
    if expected_sha and not re.fullmatch(r"[0-9a-f]{40}", expected_sha):
        raise config.error("expected_remote_sha must be a 40-character hexadecimal commit SHA")
    _remove_obsolete_guard(host, target, config)
    args = _push_args(remote, push_branch, set_upstream, expected_sha)
    refreshed = False
    try:
        output = host._git_output(target, *args)
    except config.error as exc:
        if not retryable_git_auth_failure(str(exc)):
            raise
        host.authorize_local_git(repository, destination, remote=remote)
        _check_authority(host, target, config, repository, account_id)
        _check_remote(host, target, remote, frozenset({expected.removesuffix(".git")}), config)
        output = host._git_output(target, *args)
        refreshed = True
    return {
        "pushed": True,
        "credential_refreshed": refreshed,
        config.resource_key: repository,
        "workspace": target.relative_to(host.workspace_root.resolve(strict=False)).as_posix(),
        "remote": remote,
        "branch": push_branch,
        "head": host._git_output(target, "rev-parse", "HEAD"),
        "account_id": account_id,
        "git_output": re.sub(r"(https?://)[^\s/@]+@", r"\1[redacted]@", output)[-2048:],
    }
