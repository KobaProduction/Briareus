"""Linux rootless PID-namespace adapter for short Core process authority."""

from __future__ import annotations

import asyncio as asyncio
import os
import signal
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path

from hand_runtime.process_lease_application import ProcessLeaseController
from hand_runtime.process_lease_domain import (
    LeaseExpiryInput,
    LeaseIdentityInput,
    ProcessAuthority,
    ProcessInventory,
    ProcessState,
)

__all__ = ["ProcessLease"]


def _require_private_supervisor(uid: int) -> None:
    mapping = [
        tuple(map(int, line.split()))
        for line in Path("/proc/self/uid_map").read_text().splitlines()
    ]
    if (
        os.geteuid() != 0
        or type(uid) is not int
        or uid <= 0
        or not mapping
        or mapping[0][0] != 0
        or mapping[0][1] == 0
    ):
        raise ValueError("A rootless private worker supervisor is required")


def _owned_process(path: Path, uid: int) -> ProcessState | None:
    if not path.name.isdigit():
        return None
    try:
        fields = dict(
            line.split(":", 1) for line in (path / "status").read_text().splitlines() if ":" in line
        )
    except (FileNotFoundError, ProcessLookupError):
        return None
    uids = tuple(map(int, fields["Uid"].split()))
    state = fields["State"].strip()[0]
    # Chromium descendants may change individual UIDs inside their sandbox.
    if uid in uids and state not in {"Z", "X"}:
        return ProcessState(int(path.name), state)
    return None


class ProcessLease(ProcessLeaseController):
    def __init__(self, uid: int = 1000) -> None:
        _require_private_supervisor(uid)
        super().__init__(uid)

    async def grant(self, identity_tuple: LeaseIdentityInput, expires_at: LeaseExpiryInput) -> bool:
        authority = ProcessAuthority.parse(identity_tuple, expires_at)
        return await super().grant(authority.identity, authority.expires_at)

    def _processes(self) -> ProcessInventory:
        processes: list[ProcessState] = []
        for path in Path("/proc").iterdir():
            process = _owned_process(path, self.uid)
            if process is not None:
                processes.append(process)
        return ProcessInventory(tuple(processes))

    @staticmethod
    def _signal(processes: Iterable[int], action: int) -> None:
        for pid in processes:
            with suppress(ProcessLookupError):
                os.kill(pid, action)

    def _terminate(self, processes: Iterable[int]) -> None:
        self._signal(processes, signal.SIGKILL)

    def _stop(self, processes: Iterable[int]) -> None:
        self._signal(processes, signal.SIGSTOP)

    def _resume(self, processes: Iterable[int]) -> None:
        self._signal(processes, signal.SIGCONT)
