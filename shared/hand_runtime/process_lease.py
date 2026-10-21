"""Short Core authority over processes in one rootless worker PID namespace.

The trusted supervisor is UID 0; its effect processes have a dedicated UID.
No Docker socket, host PID namespace or writable cgroup mount is required.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path


class ProcessLease:
    def __init__(self, uid=1000):
        mapping = [tuple(map(int, line.split())) for line in Path("/proc/self/uid_map").read_text().splitlines()]
        if (os.geteuid() != 0 or type(uid) is not int or uid <= 0
            or not mapping or mapping[0][0] != 0 or mapping[0][1] == 0):
            raise ValueError("A rootless private worker supervisor is required")
        self.uid = uid
        self.identity = None
        self.expires_at = 0.0
        self._deadline = 0.0
        self.paused = False
        self._lock = asyncio.Lock()

    @property
    def status(self):
        if self.identity is None:
            return "unleased"
        return "paused" if self.paused else "active"

    def _processes(self):
        result = {}
        for path in Path("/proc").iterdir():
            if not path.name.isdigit():
                continue
            try:
                fields = dict(line.split(":", 1) for line in (path / "status").read_text().splitlines() if ":" in line)
            except (FileNotFoundError, ProcessLookupError):
                continue
            uids = tuple(map(int, fields["Uid"].split()))
            # Include descendants whose real/effective/saved/fs UID changed
            # inside Chromium's sandbox, as long as any visible UID is ours.
            if self.uid in uids and fields["State"].strip()[0] not in {"Z", "X"}:
                result[int(path.name)] = fields["State"].strip()[0]
        return result

    @staticmethod
    def _signal(processes, action):
        for pid in processes:
            try:
                os.kill(pid, action)
            except ProcessLookupError:
                pass

    async def _kill(self):
        self.identity = None
        self.expires_at = self._deadline = 0.0
        self.paused = False
        for _ in range(40):
            processes = self._processes()
            if not processes:
                return
            self._signal(processes, signal.SIGKILL)
            await asyncio.sleep(0.01)
        raise RuntimeError("Worker process termination could not be confirmed")

    async def kill(self):
        async with self._lock:
            await self._kill()

    async def grant(self, identity_tuple, expires_at):
        """Resume only the same actor/session/revision; return whether it survived."""
        if (not isinstance(identity_tuple, tuple) or len(identity_tuple) != 3
            or any(not isinstance(item, str) or not item for item in identity_tuple[:2])
            or type(identity_tuple[2]) is not int or identity_tuple[2] < 1
            or not isinstance(expires_at, (int, float)) or not 0 < expires_at - time.time() <= 5):
            raise ValueError("Current bounded Core process authority is required")
        async with self._lock:
            preserved = self.identity == identity_tuple
            if self.identity is not None and not preserved:
                await self._kill()
            self.identity = identity_tuple
            self.expires_at = expires_at
            self._deadline = time.monotonic() + max(0, expires_at - time.time())
            if self.paused:
                self._signal(self._processes(), signal.SIGCONT)
            self.paused = False
            return preserved

    async def pause_expired(self):
        """Stop the entire UID and confirm stable stopped state, or kill it."""
        async with self._lock:
            if self.identity is None or self.paused or time.monotonic() < self._deadline:
                return self.paused
            try:
                stable = None
                for _ in range(30):
                    before = self._processes()
                    self._signal(before, signal.SIGSTOP)
                    await asyncio.sleep(0.01)
                    after = self._processes()
                    if set(after) == stable and all(state in {"T", "t"} for state in after.values()):
                        self.paused = True
                        return True
                    stable = set(after) if all(state in {"T", "t"} for state in after.values()) else None
                raise RuntimeError("Worker pause could not be confirmed")
            except BaseException:
                await self._kill()
                raise
