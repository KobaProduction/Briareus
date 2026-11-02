"""Credential-ephemeral Git execution with a closed configuration environment."""

import os
import select
import signal
import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from hand_runtime.runtime_policy import runtime_policy


@dataclass(frozen=True, slots=True)
class GitEnvironment:
    variables: tuple[tuple[str, str], ...] = field(repr=False)


def git_environment(auth_scope: str, auth_header: str) -> GitEnvironment:
    env = {
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        "HOME": "/home/hand",
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": "/dev/null",
        "GIT_CONFIG_SYSTEM": "/dev/null",
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_LITERAL_PATHSPECS": "1",
    }
    for key in (
        "HTTP_PROXY",
        "HTTPS_PROXY",
        "ALL_PROXY",
        "NO_PROXY",
        "http_proxy",
        "https_proxy",
        "all_proxy",
        "no_proxy",
    ):
        if key in os.environ:
            env[key] = os.environ[key]
    config = [
        ("credential.helper", ""),
        ("core.hooksPath", "/dev/null"),
        ("core.fsmonitor", "false"),
        ("protocol.file.allow", "never"),
        ("protocol.ext.allow", "never"),
        ("http.followRedirects", "false"),
    ]
    if auth_header:
        config.append(("http." + auth_scope + ".extraHeader", auth_header))
    env["GIT_CONFIG_COUNT"] = str(len(config))
    for index, (key, value) in enumerate(config):
        env[f"GIT_CONFIG_KEY_{index}"] = key
        env[f"GIT_CONFIG_VALUE_{index}"] = value
    return GitEnvironment(tuple(env.items()))


class GitProcess:
    """One fixed executable, closed stdin/stderr, bounded stdout and whole-group cleanup."""

    def __init__(
        self, target: Path, arguments: tuple[str, ...], environment: GitEnvironment
    ) -> None:
        self._reaped = False
        self._status = 0
        reader, writer = os.pipe2(os.O_CLOEXEC)
        try:
            self._pid = self._spawn(target, arguments, environment, reader, writer)
        except BaseException:
            os.close(reader)
            raise
        finally:
            os.close(writer)
        self._reader = reader

    @staticmethod
    def _spawn(
        target: Path,
        arguments: tuple[str, ...],
        environment: GitEnvironment,
        reader: int,
        writer: int,
    ) -> int:
        null = os.open(os.devnull, os.O_RDWR | os.O_CLOEXEC)
        try:
            return os.posix_spawn(
                "/usr/bin/git",
                ("git", "-C", str(target), *arguments),
                dict(environment.variables),
                setsid=True,
                file_actions=[
                    (os.POSIX_SPAWN_DUP2, null, 0),
                    (os.POSIX_SPAWN_DUP2, writer, 1),
                    (os.POSIX_SPAWN_DUP2, null, 2),
                    (os.POSIX_SPAWN_CLOSE, reader),
                    (os.POSIX_SPAWN_CLOSE, writer),
                    (os.POSIX_SPAWN_CLOSE, null),
                ],
            )
        finally:
            os.close(null)

    def capture(self, timeout: float | None) -> str:
        output = bytearray()
        eof = False
        deadline = None if timeout is None else time.monotonic() + timeout
        while not (self._reaped and eof):
            remaining = 0.05 if deadline is None else deadline - time.monotonic()
            if remaining <= 0:
                raise ValueError("NODE_GIT_OPERATION_UNAVAILABLE")
            readable, _, _ = select.select(
                [] if eof else [self._reader], [], [], min(remaining, 0.05)
            )
            if readable:
                chunk = os.read(self._reader, 65536)
                eof = not chunk
                output.extend(chunk)
                if len(output) > 262144:
                    raise ValueError("NODE_GIT_OUTPUT_LIMIT")
            self._poll()
        if self._status != 0:
            raise ValueError("NODE_GIT_OPERATION_FAILED")
        return output.decode("utf-8", "replace").strip()

    def _poll(self) -> None:
        if not self._reaped:
            pid, status = os.waitpid(self._pid, os.WNOHANG)
            if pid:
                self._status = status
                self._reaped = True

    def close(self) -> None:
        try:
            os.killpg(self._pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        finally:
            os.close(self._reader)
            if not self._reaped:
                os.waitpid(self._pid, 0)
                self._reaped = True


def run_git(target: Path, *arguments: str, auth_scope: str = "", auth_header: str = "") -> str:
    try:
        process = GitProcess(target, arguments, git_environment(auth_scope, auth_header))
        try:
            return process.capture(runtime_policy().execution_timeout_seconds)
        finally:
            process.close()
    except OSError:
        # Provider stderr may contain URLs, headers or an account token and is discarded.
        raise ValueError("NODE_GIT_OPERATION_UNAVAILABLE") from None


@contextmanager
def repository_lock(canonical: Path) -> Iterator[None]:
    import fcntl

    descriptor = os.open(
        canonical.with_suffix(".lock"), os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)
