"""Remove only the fixed Xvfb endpoints after the supervisor kills its cohort.

Runs as the same unprivileged UID as Xvfb. Never use this while a worker is
alive: ProcessLease.kill() must confirm termination before this helper runs.
"""
from __future__ import annotations

import os
from pathlib import Path
import stat


def clean_display(root: Path = Path("/tmp")) -> None:
    uid = os.geteuid()
    with_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        candidates = []
        try:
            lock = os.stat(".X99-lock", dir_fd=with_fd, follow_symlinks=False)
        except FileNotFoundError:
            pass
        else:
            if not (stat.S_ISREG(lock.st_mode) and lock.st_uid == uid
                    and lock.st_nlink == 1 and lock.st_size <= 32):
                raise ValueError("Unexpected Xvfb lock ownership or type")
            candidates.append((with_fd, ".X99-lock"))
        socket_fd = None
        try:
            socket_fd = os.open(".X11-unix", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=with_fd)
        except FileNotFoundError:
            pass
        try:
            if socket_fd is not None:
                try:
                    endpoint = os.stat("X99", dir_fd=socket_fd, follow_symlinks=False)
                except FileNotFoundError:
                    pass
                else:
                    if not (stat.S_ISSOCK(endpoint.st_mode) and endpoint.st_uid == uid):
                        raise ValueError("Unexpected Xvfb endpoint ownership or type")
                    candidates.append((socket_fd, "X99"))
            for directory, name in candidates:
                os.unlink(name, dir_fd=directory)
        finally:
            if socket_fd is not None:
                os.close(socket_fd)
    finally:
        os.close(with_fd)


if __name__ == "__main__":
    if os.geteuid() != 1000:
        raise ValueError("Unprivileged Xvfb cleanup required")
    clean_display()
