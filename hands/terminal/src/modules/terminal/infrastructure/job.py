"""Live native job handles are owned only by the process adapter."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Job:
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
    log_truncated: bool = False
    process: asyncio.subprocess.Process | None = None
    master_fd: int | None = None
    reader_task: asyncio.Task[None] | None = None
    watcher_task: asyncio.Task[None] | None = None
    timeout_seconds: float | None = None
    cancel_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
