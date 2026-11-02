"""Kernel-held local writer exclusion, independent of remote database leases."""

import os
from pathlib import Path
from typing import Protocol

from node_agent.domain.placement import OperationConflict


class WriterLock(Protocol):
    def acquire(self) -> None: ...

    def release(self) -> None: ...


class ControllerLock:
    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> None:
        import fcntl

        if self._fd is not None:
            return
        descriptor = os.open(self._path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BaseException:
            os.close(descriptor)
            raise OperationConflict("Only one controller may own this node runtime") from None
        self._fd = descriptor

    def release(self) -> None:
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None
