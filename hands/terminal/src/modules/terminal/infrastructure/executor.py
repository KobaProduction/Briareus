"""Owner-local native execution policies over the shared Terminal core."""

from __future__ import annotations

import asyncio as asyncio
import logging as logging
import os
import re
import time as time
from contextlib import suppress as suppress

from common.admin_api_client import AdminApiClient as AdminApiClient
from common.settings import TerminalSettings as TerminalSettings
from modules.terminal._offline_executor import (
    OfflineExecutorUnavailable as OfflineExecutorUnavailable,
)
from modules.terminal._offline_executor import require_offline_executor as require_offline_executor
from modules.terminal.domain.policy import JobRuntimeLimit as JobRuntimeLimit
from modules.terminal.domain.policy import TerminalError as TerminalError
from project_runtime_client.terminal.infrastructure.executor import (
    TerminalManagerBase as _SharedTerminalManager,
)
from project_runtime_client.terminal.infrastructure.executor import _timestamp as _timestamp
from project_runtime_client.terminal.infrastructure.job_files import JobFileRepository
from runtime_peer.terminal_receipts import JobExecution

from .job import Job as Job

logger = logging.getLogger(__name__)


class TerminalManager(_SharedTerminalManager[Job, float | None]):
    _logger = logger

    def __init__(self, settings: TerminalSettings, admin_api: AdminApiClient | None = None) -> None:
        self.settings = settings
        self.admin_api = admin_api
        self.workspace_root = settings.workspace_root
        self.projects_root = self.workspace_root / "projects"
        self.home = settings.home
        self.jobs_root = self.home / ".terminal" / "jobs"
        self._human_namespace = os.environ.get("TERMINAL_JOB_NAMESPACE")
        self._creation_id: str | None = None
        self._visible_jobs: frozenset[str] | None = None
        if self._human_namespace is not None:
            if re.fullmatch(r"human-[a-f0-9]{64}", self._human_namespace) is None:
                raise TerminalError("Verified human job namespace required")
            self.jobs_root = self.jobs_root / self._human_namespace
        self._jobs: dict[str, Job] = {}
        self._job_activity: dict[str, float] = {}
        self._idle_task: asyncio.Task[None] | None = None
        self._job_files = JobFileRepository(self.jobs_root, Job)
        self._job_factory = Job
        self._prepare_storage()
        self._load_persisted_jobs()

    def begin_human_command(
        self,
        namespace: str,
        creation_id: str | None,
        allowed_jobs: tuple[str, ...] | None,
    ) -> None:
        if namespace != self._human_namespace:
            raise TerminalError("Human job namespace changed")
        self._creation_id = creation_id
        self._visible_jobs = frozenset(allowed_jobs) if allowed_jobs is not None else None

    def end_human_command(self) -> None:
        self._creation_id = None
        self._visible_jobs = None

    def _new_job_id(self) -> str:
        return self._creation_id or super()._new_job_id()

    def _job_visible(self, job_id: str) -> bool:
        return self._visible_jobs is None or job_id in self._visible_jobs

    @staticmethod
    def _require_offline_executor() -> None:
        try:
            require_offline_executor()
        except OfflineExecutorUnavailable as exc:
            raise TerminalError(str(exc)) from exc

    async def terminal_exec(
        self,
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
    ) -> JobExecution:
        """Start once and return a bounded observation of a retained command job."""
        requested_limit = (
            self.settings.max_exec_output_bytes if max_output_bytes is None else max_output_bytes
        )
        if requested_limit <= 0:
            raise TerminalError("max_output_bytes must be > 0")
        limit = min(requested_limit, self.settings.max_exec_output_bytes)
        started = await self.job_start(
            workspace_id,
            command,
            cwd=cwd,
            env=env,
            interactive=False,
            timeout_seconds=timeout_seconds,
        )
        job_id = started.job_id
        await self.job_wait(job_id, timeout_seconds=1)
        output = await self.job_read(job_id, cursor=0, max_bytes=limit, wait_seconds=0)
        current = self.job_status(job_id)
        return JobExecution(
            job_id=current.job_id,
            workspace_id=current.workspace_id,
            label=current.label,
            cwd=current.cwd,
            interactive=current.interactive,
            state=current.state,
            pid=current.pid,
            exit_code=current.exit_code,
            signal=current.signal,
            created_at=current.created_at,
            started_at=current.started_at,
            ended_at=current.ended_at,
            duration_seconds=current.duration_seconds,
            output_bytes=current.output_bytes,
            output_truncated=current.output_truncated,
            timeout_seconds=current.timeout_seconds,
            command=command,
            stdout=output.output,
            stderr="",
            output=output.output,
            output_stream="combined",
            next_cursor=output.next_cursor,
            eof=output.eof,
            stdout_truncated=output.output_truncated
            or output.total_output_bytes > output.next_cursor,
            stderr_truncated=False,
            timed_out=current.state == "timed_out",
        )

    def _job_runtime_limit(self, timeout_seconds: float | None) -> float | None:
        self._runtime_policy()
        from hand_runtime.runtime_policy import runtime_policy

        runtime_limit = runtime_policy().execution_timeout_seconds
        requested_timeout = float(timeout_seconds) if timeout_seconds is not None else None
        return JobRuntimeLimit(requested_timeout, runtime_limit).seconds

    def _job_started(self, job: Job) -> None:
        self._job_activity[job.job_id] = time.monotonic()
        from hand_runtime.runtime_policy import runtime_policy

        if runtime_policy().terminal_idle_seconds is not None and (
            self._idle_task is None or self._idle_task.done()
        ):
            self._idle_task = asyncio.create_task(self._close_idle_jobs())

    async def _close_idle_jobs(self) -> None:
        from hand_runtime.runtime_policy import runtime_policy

        while any(job.state in {"running", "cancelling"} for job in self._jobs.values()):
            idle = runtime_policy().terminal_idle_seconds
            if idle is None:
                return
            await asyncio.sleep(min(5, idle))
            for job_id, job in list(self._jobs.items()):
                if (
                    job.state == "running"
                    and time.monotonic() - self._job_activity.get(job_id, time.monotonic()) >= idle
                ):
                    with suppress(TerminalError):
                        await self.job_cancel(job_id, grace_seconds=0.5)

    def _get_job(self, job_id: str) -> Job:
        if not self._job_visible(job_id):
            raise TerminalError("Job not in current authority scope")
        job = self._jobs.get(job_id.strip())
        if job is None:
            raise TerminalError(f"job not found: {job_id}")
        self._job_activity[job.job_id] = time.monotonic()
        return job
