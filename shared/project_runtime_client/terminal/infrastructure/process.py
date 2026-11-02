"""Native shell/PTY creation with exact failure cleanup before job registration."""

import asyncio
import fcntl
import os
import pty
import shutil
import struct
import termios
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from project_runtime_client.terminal.domain.policy import TerminalSize


@dataclass(frozen=True, slots=True)
class SpawnedProcess:
    process: asyncio.subprocess.Process
    master_fd: int | None


def resize_terminal(fd: int, cols: int, rows: int) -> None:
    TerminalSize(cols, rows)
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


async def spawn_shell(
    *,
    command: str,
    shell: str,
    workdir: Path,
    environment: dict[str, str],
    interactive: bool,
    cols: int,
    rows: int,
    job_dir: Path,
    log_path: Path,
) -> SpawnedProcess:
    master_fd: int | None = None
    slave_fd: int | None = None
    try:
        prepare_log(log_path)
        if interactive:
            master_fd, slave_fd = pty.openpty()
            os.set_blocking(master_fd, False)
            resize_terminal(master_fd, cols, rows)
            process = await asyncio.create_subprocess_shell(
                command,
                executable=shell,
                cwd=workdir,
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                start_new_session=True,
            )
        else:
            process = await asyncio.create_subprocess_shell(
                command,
                executable=shell,
                cwd=workdir,
                env=environment,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
    except BaseException:
        if master_fd is not None:
            with suppress(OSError):
                os.close(master_fd)
        shutil.rmtree(job_dir, ignore_errors=True)
        raise
    finally:
        if slave_fd is not None:
            with suppress(OSError):
                os.close(slave_fd)
    return SpawnedProcess(process, master_fd)


def prepare_log(path: Path) -> None:
    path.touch(exist_ok=False)


@dataclass(frozen=True, slots=True)
class ProcessEnvironment:
    values: dict[str, str]
