"""Typed boundary for live native job handles and owner-local recovery factories."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Protocol


class JobState(Protocol):
    job_id: str
    workspace_id: str
    command: str
    cwd: str
    interactive: bool
    label: str
    state: str
    created_at: float
    started_at: float
    ended_at: float | None
    exit_code: int | None
    signal_number: int | None
    pid: int | None
    log_path: Path
    metadata_path: Path
    log_truncated: bool
    process: asyncio.subprocess.Process | None
    master_fd: int | None
    reader_task: asyncio.Task[None] | None
    watcher_task: asyncio.Task[None] | None
    cancel_lock: asyncio.Lock

    @property
    def timeout_seconds(self) -> float | None: ...


class JobFactory[JobT: JobState, TimeoutT: float | None](Protocol):
    def __call__(
        self,
        *,
        job_id: str,
        workspace_id: str,
        command: str,
        cwd: str,
        interactive: bool,
        label: str,
        state: str,
        created_at: float,
        started_at: float,
        ended_at: float | None,
        exit_code: int | None,
        signal_number: int | None,
        pid: int | None,
        log_path: Path,
        metadata_path: Path,
        log_truncated: bool,
        timeout_seconds: TimeoutT,
        process: asyncio.subprocess.Process | None = None,
        master_fd: int | None = None,
    ) -> JobT: ...
