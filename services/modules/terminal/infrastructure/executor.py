"""Owner-local native execution policies over the shared Terminal core."""

from __future__ import annotations

import asyncio as asyncio
import logging as logging
import math as math
import time as time

from common.admin_api_client import AdminApiClient as AdminApiClient
from common.settings import TerminalSettings as TerminalSettings
from modules.terminal.domain.policy import TerminalError as TerminalError
from project_runtime_client.terminal.infrastructure.executor import (
    TerminalManagerBase as _SharedTerminalManager,
)
from project_runtime_client.terminal.infrastructure.executor import _timestamp as _timestamp
from project_runtime_client.terminal.infrastructure.job_files import JobFileRepository
from runtime_peer.terminal_receipts import DirectExecution

from .job import Job as Job

logger = logging.getLogger(__name__)
_DRAIN_GRACE_SECONDS = 2.0


class TerminalManager(_SharedTerminalManager[Job, float]):
    _logger = logger

    def __init__(self, settings: TerminalSettings, admin_api: AdminApiClient | None = None) -> None:
        self.settings = settings
        self.admin_api = admin_api
        self.workspace_root = settings.workspace_root
        self.projects_root = self.workspace_root / "projects"
        self.home = settings.home
        self.jobs_root = self.home / ".terminal" / "jobs"
        self._jobs: dict[str, Job] = {}
        self._job_files = JobFileRepository(self.jobs_root, Job)
        self._job_factory = Job
        self._prepare_storage()
        self._load_persisted_jobs()

    async def terminal_exec(
        self,
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        timeout_seconds: float = 60,
        max_output_bytes: int | None = None,
    ) -> DirectExecution:
        if not command.strip():
            raise TerminalError("command is required")
        workspace_id = self._workspace_id(workspace_id)
        workdir = self.resolve_cwd(workspace_id, cwd)
        requested_limit = max_output_bytes or self.settings.max_exec_output_bytes
        if requested_limit <= 0:
            raise TerminalError("max_output_bytes must be > 0")
        limit = min(requested_limit, self.settings.max_exec_output_bytes)
        policy = self._runtime_policy()
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise TerminalError("timeout_seconds must be finite and positive")
        effective_timeout = min(max(0.1, timeout_seconds), float(policy.max_exec_timeout_seconds))
        started = time.time()
        process = await asyncio.create_subprocess_shell(
            command,
            executable=self.settings.shell,
            cwd=workdir,
            env=self._environment(env).values,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            start_new_session=True,
        )
        if process.stdout is None or process.stderr is None:
            raise TerminalError("Command output streams unavailable")
        stdout_task = asyncio.create_task(self._drain_bounded(process.stdout, limit))
        stderr_task = asyncio.create_task(self._drain_bounded(process.stderr, limit))
        timed_out = False
        try:
            await asyncio.wait_for(process.wait(), timeout=effective_timeout)
        except TimeoutError:
            timed_out = True
            await self._terminate_process(process)
        except asyncio.CancelledError:
            try:
                await self._terminate_process(process)
            finally:
                stdout_task.cancel()
                stderr_task.cancel()
                await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)
            raise
        streams = asyncio.gather(stdout_task, stderr_task)
        try:
            await asyncio.wait_for(asyncio.shield(streams), timeout=_DRAIN_GRACE_SECONDS)
        except TimeoutError:
            stdout_task.cancel()
            stderr_task.cancel()
        (stdout, stdout_truncated), (stderr, stderr_truncated) = await streams
        ended = time.time()
        stdout_value = stdout.decode("utf-8", errors="replace")
        stderr_value = stderr.decode("utf-8", errors="replace")
        return DirectExecution(
            workspace_id=workspace_id,
            command=command,
            cwd=str(workdir),
            exit_code=process.returncode,
            timed_out=timed_out,
            stdout=stdout_value,
            stderr=stderr_value,
            stdout_truncated=stdout_truncated,
            stderr_truncated=stderr_truncated,
            started_at=_timestamp(started),
            ended_at=_timestamp(ended),
            duration_seconds=round(ended - started, 3),
            timeout_seconds=effective_timeout,
        )

    def _job_runtime_limit(self, timeout_seconds: float | None) -> float:
        policy = self._runtime_policy()
        requested_timeout = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else float(policy.max_job_runtime_seconds)
        )
        if not math.isfinite(requested_timeout) or requested_timeout <= 0:
            raise TerminalError("timeout_seconds must be finite and positive")
        return min(max(0.1, requested_timeout), float(policy.max_job_runtime_seconds))

    def _job_wait_timeout(self, job: Job) -> float:
        return max(0.1, job.timeout_seconds)

    def _get_job(self, job_id: str) -> Job:
        job = self._jobs.get(job_id.strip())
        if job is None:
            raise TerminalError(f"job not found: {job_id}")
        return job
