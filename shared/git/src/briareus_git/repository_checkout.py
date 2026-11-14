from __future__ import annotations

import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

from briareus_json_values import JsonObject
from briareus_server_mount import ServerMountError, resolve_mount_path


class RepositoryCheckoutError(RuntimeError):
    pass


def retryable_git_auth_failure(message: str) -> bool:
    """Only stale/missing Git credentials qualify for one provider-owned refresh."""
    lowered = message.casefold()
    return any(
        reason in lowered
        for reason in (
            "invalid username or token",
            "authentication failed",
            "could not read username",
            "could not read password",
            "http basic: access denied",
            "terminal prompts disabled",
        )
    )


def checkout_destination(root: Path, value: str) -> Path:
    """Resolve a Git checkout name; MCP destinations are mount-relative, never absolute."""
    raw = value.strip().replace("\\", "/")
    if raw.startswith("/") or re.match(r"^[a-zA-Z]:/", raw):
        resolved_root = root.resolve(strict=False)
        candidate = Path(raw).resolve(strict=False)
        if candidate.is_relative_to(resolved_root) and candidate != resolved_root:
            relative = candidate.relative_to(resolved_root).as_posix()
            raise RepositoryCheckoutError(
                f"destination must be relative to SERVER_MOUNT_PATH; "
                f"use destination={relative!r}, not an absolute path. "
                "Pass the path returned by checkout_repository."
            )
        raise RepositoryCheckoutError(
            "destination must be relative to SERVER_MOUNT_PATH "
            "(e.g. 'projects/example/repo'), not an absolute filesystem path. "
            "Pass the path returned by checkout_repository."
        )
    try:
        return resolve_mount_path(root, raw)
    except ServerMountError as exc:
        raise RepositoryCheckoutError(str(exc)) from exc


def _destination(root: Path, value: str) -> Path:
    return checkout_destination(root, value)


def _run(
    command: list[str],
    *,
    env: dict[str, str],
    timeout_seconds: int,
) -> None:
    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired as exc:
        raise RepositoryCheckoutError("git checkout timed out") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-2048:]
        raise RepositoryCheckoutError(
            f"git command failed with exit code {result.returncode}: {detail}"
        )


def _attempt_checkout(
    target: Path,
    clone_url: str,
    normalized_mode: str,
    ref: str,
    auth_scope: str,
    header: str,
    timeout_seconds: int,
) -> None:
    temporary = target.parent / (f".{target.name}.checkout-{uuid.uuid4().hex}")
    env = os.environ.copy()
    if header:
        if not auth_scope:
            raise RepositoryCheckoutError("auth_scope is required when auth_header is set")
        env.update(
            {
                "GIT_CONFIG_COUNT": "1",
                "GIT_CONFIG_KEY_0": f"http.{auth_scope}.extraheader",
                "GIT_CONFIG_VALUE_0": header,
                "GIT_TERMINAL_PROMPT": "0",
            }
        )
    else:
        env["GIT_TERMINAL_PROMPT"] = "0"

    clone = ["git", "clone"]
    if normalized_mode == "snapshot":
        clone += ["--depth", "1", "--no-tags"]
    if ref:
        clone += ["--branch", ref]
    clone += ["--", clone_url, str(temporary)]

    try:
        _run(clone, env=env, timeout_seconds=timeout_seconds)
        if normalized_mode == "snapshot":
            shutil.rmtree(temporary / ".git", ignore_errors=True)
        os.replace(temporary, target)
    finally:
        if temporary.exists():
            shutil.rmtree(temporary, ignore_errors=True)


def checkout_repository(
    clone_url: str,
    destination: str,
    *,
    workspace_root: Path,
    mode: str = "snapshot",
    ref: str = "",
    overwrite: bool = False,
    auth_scope: str = "",
    auth_header: str = "",
    fallback_without_auth: bool = False,
    timeout_seconds: int = 300,
) -> JsonObject:
    normalized_mode = mode.strip().casefold()
    if normalized_mode not in {"snapshot", "git"}:
        raise RepositoryCheckoutError("mode must be 'snapshot' or 'git'")

    root = workspace_root.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True)
    target = _destination(root, destination)
    if target.exists():
        if not overwrite:
            raise RepositoryCheckoutError(f"destination already exists: {destination}")
        if target.is_dir():
            shutil.rmtree(target)
        else:
            target.unlink()
    target.parent.mkdir(parents=True, exist_ok=True)

    try:
        _attempt_checkout(
            target, clone_url, normalized_mode, ref, auth_scope, auth_header, timeout_seconds
        )
        auth_mode = "authenticated" if auth_header else "anonymous"
    except RepositoryCheckoutError:
        if not auth_header or not fallback_without_auth:
            raise
        _attempt_checkout(target, clone_url, normalized_mode, ref, auth_scope, "", timeout_seconds)
        auth_mode = "anonymous_fallback"

    return {
        "path": target.relative_to(root).as_posix(),
        "mode": normalized_mode,
        "ref": ref,
        "git_metadata": normalized_mode == "git",
        "auth_mode": auth_mode,
    }
