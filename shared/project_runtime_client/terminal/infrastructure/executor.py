from __future__ import annotations

import asyncio
import fcntl as fcntl
import grp
import json
import logging
import math
import os
import shutil
import signal
import struct as struct
import termios as termios
import time
import uuid
from abc import ABC, abstractmethod
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path

from project_runtime_client.terminal.domain.policy import (
    EnvironmentVariable,
    JobPage,
    RetentionPolicy,
    WorkspaceIdentity,
)
from project_runtime_client.terminal.domain.policy import (
    TerminalError as TerminalError,
)
from project_runtime_client.terminal.domain.policy import (
    TerminalSize as TerminalSize,
)
from runtime_peer.terminal_receipts import (
    DiskUsage,
    JobCleanup,
    JobDeleted,
    JobList,
    JobRead,
    JobResize,
    JobStatus,
    JobWrite,
    RuntimeGroup,
    SerialDevice,
    TerminalStatus,
    WorkspaceCreated,
    WorkspaceDeleted,
    WorkspaceInfo,
    WorkspaceList,
    WorkspaceSummary,
)
from service_runtime.admin_api_client import AdminApiClient, AdminApiClientError
from service_runtime.owner_settings import TerminalSettings
from service_runtime.runtime_policy_contracts import TerminalRuntimePolicy

from .job_contract import JobFactory, JobState
from .job_files import JobFileRepository
from .process import ProcessEnvironment, spawn_shell
from .process import resize_terminal as _resize_terminal

_DRAIN_GRACE_SECONDS = 2.0


def _timestamp(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat()


class TerminalManagerBase[JobT: JobState, TimeoutT: float | None](ABC):
    settings: TerminalSettings
    admin_api: AdminApiClient | None
    workspace_root: Path
    projects_root: Path
    home: Path
    jobs_root: Path
    _jobs: dict[str, JobT]
    _job_files: JobFileRepository[JobT]
    _job_factory: JobFactory[JobT, TimeoutT]
    _logger: logging.Logger

    @abstractmethod
    def _get_job(self, job_id: str) -> JobT:
        raise NotImplementedError

    def _job_wait_timeout(self, job: JobT) -> float | None:
        return job.timeout_seconds

    @staticmethod
    def _require_offline_executor() -> None:
        return

    @abstractmethod
    def _job_runtime_limit(self, timeout_seconds: float | None) -> TimeoutT:
        raise NotImplementedError

    def _job_started(self, _job: JobT) -> None:
        return

    def _new_job_id(self) -> str:
        return uuid.uuid4().hex

    def _job_visible(self, _job_id: str) -> bool:
        return True

    async def job_start(
        self,
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        interactive: bool = False,
        label: str = "",
        cols: int = 120,
        rows: int = 40,
        timeout_seconds: float | None = None,
    ) -> JobStatus:
        if not command.strip():
            raise TerminalError("command is required")
        self._require_offline_executor()
        workspace_id = self._workspace_id(workspace_id)
        workdir = self.resolve_cwd(workspace_id, cwd)
        effective_timeout = self._job_runtime_limit(timeout_seconds)
        if interactive and (not 1 <= cols <= 1000):
            raise TerminalError("terminal cols must be between 1 and 1000")
        if interactive and (not 1 <= rows <= 1000):
            raise TerminalError("terminal rows must be between 1 and 1000")
        environment = self._environment(env).values
        now = time.time()
        job_id = self._new_job_id()
        job_dir = self._job_dir(job_id)
        job_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
        log_path = job_dir / "output.log"
        metadata_path = job_dir / "metadata.json"
        spawned = await spawn_shell(
            command=command,
            shell=self.settings.shell,
            workdir=workdir,
            environment=environment,
            interactive=interactive,
            cols=cols,
            rows=rows,
            job_dir=job_dir,
            log_path=log_path,
        )
        process, master_fd = spawned.process, spawned.master_fd
        job = self._job_factory(
            job_id=job_id,
            workspace_id=workspace_id,
            command=command,
            cwd=str(workdir),
            interactive=interactive,
            label=label,
            state="running",
            created_at=now,
            started_at=now,
            ended_at=None,
            exit_code=None,
            signal_number=None,
            pid=process.pid,
            log_path=log_path,
            metadata_path=metadata_path,
            log_truncated=False,
            process=process,
            master_fd=master_fd,
            timeout_seconds=effective_timeout,
        )
        self._jobs[job_id] = job
        self._job_started(job)
        await self._start_job_observers(job)
        return self._job_public(job)

    async def _watch_job(self, job: JobT) -> None:
        if job.process is None:
            raise TerminalError("Job process unavailable")
        timed_out = False
        try:
            returncode = await asyncio.wait_for(
                job.process.wait(), timeout=self._job_wait_timeout(job)
            )
        except TimeoutError:
            timed_out = True
            async with job.cancel_lock:
                await self._terminate_process(job.process)
                returncode = await job.process.wait()
        if job.reader_task is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(job.reader_task), timeout=_DRAIN_GRACE_SECONDS
                )
            except TimeoutError:
                job.reader_task.cancel()
                job.log_truncated = True
            except Exception:
                job.log_truncated = True
        job.ended_at = time.time()
        job.exit_code = returncode
        job.signal_number = -returncode if returncode < 0 else None
        if timed_out:
            job.state = "timed_out"
        elif job.state == "cancelling":
            job.state = "cancelled"
        elif returncode == 0:
            job.state = "completed"
        else:
            job.state = "failed"
        job.pid = None
        job.process = None
        self._persist(job)

    def _prepare_storage(self) -> None:
        self.projects_root.mkdir(parents=True, exist_ok=True)
        self.jobs_root.mkdir(parents=True, exist_ok=True)
        self.home.mkdir(parents=True, exist_ok=True)

    def _workspace_id(self, value: str) -> str:
        return WorkspaceIdentity(value).value

    def workspace_path(self, workspace_id: str) -> Path:
        workspace_id = self._workspace_id(workspace_id)
        path = (self.projects_root / workspace_id).resolve(strict=False)
        if not path.is_relative_to(self.projects_root.resolve(strict=False)):
            raise TerminalError("workspace path escapes workspace root")
        return path

    def _require_workspace(self, workspace_id: str) -> Path:
        path = self.workspace_path(workspace_id)
        if not path.is_dir():
            raise TerminalError(f"workspace not found: {workspace_id}")
        return path

    def resolve_cwd(self, workspace_id: str, cwd: str = "") -> Path:
        base = self._require_workspace(workspace_id).resolve(strict=False)
        value = cwd.strip()
        candidate = base if not value else (base / value).resolve(strict=False)
        if not candidate.is_relative_to(base):
            raise TerminalError("cwd escapes workspace")
        if not candidate.is_dir():
            raise TerminalError(f"cwd is not a directory: {cwd}")
        return candidate

    @staticmethod
    def _tree_size_bytes(path: Path) -> int:
        total = 0
        stack = [path]
        while stack:
            current = stack.pop()
            try:
                with os.scandir(current) as iterator:
                    for item in iterator:
                        try:
                            if item.is_symlink():
                                continue
                            if item.is_dir(follow_symlinks=False):
                                stack.append(Path(item.path))
                            elif item.is_file(follow_symlinks=False):
                                total += item.stat(follow_symlinks=False).st_size
                        except FileNotFoundError:
                            continue
            except FileNotFoundError:
                continue
        return total

    def _runtime_policy(self) -> TerminalRuntimePolicy:
        if self.admin_api is None:
            return TerminalRuntimePolicy()
        try:
            return self.admin_api.terminal_runtime_policy()
        except (AdminApiClientError, ValueError):
            return TerminalRuntimePolicy()

    def _environment(self, overrides: dict[str, str] | None) -> ProcessEnvironment:
        env = {
            "HOME": str(self.home),
            "PATH": self.settings.path,
            "LANG": self.settings.lang,
            "TERM": self.settings.term,
        }
        if overrides:
            for key, value in overrides.items():
                EnvironmentVariable(key, value)
                env[key] = value
        return ProcessEnvironment(env)

    async def _terminate_process(self, process: asyncio.subprocess.Process) -> None:
        if process.returncode is not None:
            return
        if process.returncode is None:
            self._signal_process_group(process.pid, signal.SIGTERM)
        try:
            await asyncio.wait_for(process.wait(), timeout=2)
        except TimeoutError:
            if process.returncode is None:
                self._signal_process_group(process.pid, signal.SIGKILL)
            await process.wait()

    @staticmethod
    async def _drain_bounded(stream: asyncio.StreamReader, limit: int) -> tuple[bytes, bool]:
        buffer = bytearray()
        truncated = False
        try:
            while True:
                chunk = await stream.read(65536)
                if not chunk:
                    break
                remaining = max(0, limit - len(buffer))
                if remaining:
                    buffer.extend(chunk[:remaining])
                if len(chunk) > remaining:
                    truncated = True
        except asyncio.CancelledError:
            truncated = True
        return (bytes(buffer), truncated)

    def _job_dir(self, job_id: str) -> Path:
        return self.jobs_root / job_id

    @staticmethod
    def _open_owned_job_file(folder: Path, name: str, flags: int) -> int:
        return JobFileRepository._open_owned_job_file(folder, name, flags)

    def _persist(self, job: JobT) -> None:
        self._job_files._persist(job)

    def _load_persisted_jobs(self) -> None:
        for job in self._job_files.recover():
            self._jobs[job.job_id] = job
            try:
                self._persist(job)
            except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError):
                continue

    async def _start_job_observers(self, job: JobT) -> None:
        process = job.process
        if process is None:
            raise TerminalError("Job process unavailable")
        job_id, job_dir, master_fd = job.job_id, job.metadata_path.parent, job.master_fd
        try:
            self._persist(job)
            job.reader_task = asyncio.create_task(self._read_job_output(job))
            job.watcher_task = asyncio.create_task(self._watch_job(job))
        except BaseException:
            self._jobs.pop(job_id, None)
            try:
                await self._terminate_process(process)
            finally:
                pending = [task for task in (job.reader_task, job.watcher_task) if task is not None]
                for task in pending:
                    task.cancel()
                if pending:
                    await asyncio.gather(*pending, return_exceptions=True)
                if master_fd is not None:
                    with suppress(OSError):
                        os.close(master_fd)
                shutil.rmtree(job_dir, ignore_errors=True)
            raise

    async def _read_job_output(self, job: JobT) -> None:
        try:
            if job.interactive:
                await self._read_interactive(job)
            else:
                await self._read_pipe(job)
        finally:
            if job.master_fd is not None:
                with suppress(OSError):
                    os.close(job.master_fd)
                job.master_fd = None

    async def _read_interactive(self, job: JobT) -> None:
        if job.master_fd is None:
            raise TerminalError("Interactive job descriptor unavailable")
        while True:
            try:
                chunk = os.read(job.master_fd, 65536)
            except BlockingIOError:
                await asyncio.sleep(0.05)
                continue
            except OSError:
                break
            if not chunk:
                break
            self._append_job_output(job, chunk)

    async def _read_pipe(self, job: JobT) -> None:
        if job.process is None or job.process.stdout is None:
            raise TerminalError("Job output stream unavailable")
        while True:
            chunk = await job.process.stdout.read(65536)
            if not chunk:
                break
            self._append_job_output(job, chunk)

    def _append_job_output(self, job: JobT, chunk: bytes) -> None:
        with os.fdopen(
            self._open_owned_job_file(job.log_path.parent, "output.log", os.O_WRONLY | os.O_APPEND),
            "ab",
        ) as stream:
            size = os.fstat(stream.fileno()).st_size
            remaining = max(0, self.settings.max_job_log_bytes - size)
            if remaining:
                stream.write(chunk[:remaining])
        if remaining <= 0:
            if not job.log_truncated:
                job.log_truncated = True
                self._persist(job)
            return
        if remaining < len(chunk):
            job.log_truncated = True
            self._persist(job)

    _resize_fd = staticmethod(_resize_terminal)

    @staticmethod
    def _signal_process_group(pid: int | None, signum: signal.Signals) -> None:
        if pid is None:
            return
        with suppress(ProcessLookupError):
            os.killpg(pid, signum)

    def workspace_create(self, workspace_id: str) -> WorkspaceCreated:
        workspace_id = self._workspace_id(workspace_id)
        path = self.workspace_path(workspace_id)
        created = not path.exists()
        path.mkdir(parents=True, exist_ok=True)
        return WorkspaceCreated(workspace_id, str(path), created)

    def workspace_list(self) -> WorkspaceList:
        items: list[WorkspaceSummary] = []
        if self.projects_root.is_dir():
            for path in sorted(self.projects_root.iterdir(), key=lambda item: item.name.casefold()):
                if not path.is_dir():
                    continue
                stat = path.stat()
                items.append(
                    WorkspaceSummary(
                        path.name,
                        str(path),
                        _timestamp(stat.st_mtime),
                        sum(
                            1
                            for job in self._jobs.values()
                            if job.workspace_id == path.name
                            and job.state in {"running", "cancelling"}
                        ),
                    )
                )
        return WorkspaceList(tuple(items), len(items))

    def workspace_info(self, workspace_id: str) -> WorkspaceInfo:
        path = self._require_workspace(workspace_id)
        stat = path.stat()
        usage = shutil.disk_usage(path)
        return WorkspaceInfo(
            workspace_id,
            str(path),
            _timestamp(stat.st_mtime),
            DiskUsage(usage.total, usage.used, usage.free),
            tuple(
                [
                    self._job_public(job)
                    for job in sorted(
                        self._jobs.values(), key=lambda item: item.created_at, reverse=True
                    )
                    if job.workspace_id == workspace_id
                ]
            ),
        )

    async def workspace_delete(self, workspace_id: str, force: bool = False) -> WorkspaceDeleted:
        workspace_id = self._workspace_id(workspace_id)
        path = self._require_workspace(workspace_id)
        active = [
            job
            for job in self._jobs.values()
            if job.workspace_id == workspace_id and job.state in {"running", "cancelling"}
        ]
        size_bytes = self._tree_size_bytes(path)
        self._logger.info(
            "workspace cleanup decision workspace_id=%s action=delete reason=%s "
            "active_jobs=%d size_bytes=%d",
            workspace_id,
            "forced_manual_delete" if force else "manual_delete",
            len(active),
            size_bytes,
        )
        if active and (not force):
            self._logger.info(
                "workspace cleanup skipped workspace_id=%s reason=active_jobs active_jobs=%d",
                workspace_id,
                len(active),
            )
            raise TerminalError(
                "workspace has active jobs: " + ", ".join(job.job_id for job in active)
            )
        if force:
            for job in active:
                await self.job_cancel(job.job_id, grace_seconds=1)
        shutil.rmtree(path)
        self._logger.info(
            "workspace cleanup completed workspace_id=%s reason=%s freed_bytes=%d",
            workspace_id,
            "forced_manual_delete" if force else "manual_delete",
            size_bytes,
        )
        return WorkspaceDeleted(
            workspace_id, True, size_bytes, "forced_manual_delete" if force else "manual_delete"
        )

    def status(self) -> TerminalStatus:
        usage = shutil.disk_usage(self.workspace_root)
        states: dict[str, int] = {}
        for job in self._jobs.values():
            states[job.state] = states.get(job.state, 0) + 1
        job_states = states.copy()
        tool_names = (
            "bash",
            "git",
            "gh",
            "ssh",
            "wget",
            "rg",
            "make",
            "gcc",
            "g++",
            "cmake",
            "ninja",
            "python",
            "uv",
            "picocom",
            "gdb",
            "strace",
            "socat",
        )
        group_ids = sorted(set(os.getgroups()) | {os.getgid()})
        groups: list[RuntimeGroup] = []
        for group_id in group_ids:
            try:
                name = grp.getgrgid(group_id).gr_name
            except KeyError:
                name = ""
            groups.append(RuntimeGroup(group_id, name))
        serial_paths = sorted(
            {
                *Path("/dev").glob("ttyUSB*"),
                *Path("/dev").glob("ttyACM*"),
                *Path("/dev/serial/by-id").glob("*"),
            },
            key=str,
        )
        serial_devices: list[SerialDevice] = [
            SerialDevice(str(path), os.access(path, os.R_OK), os.access(path, os.W_OK))
            for path in serial_paths
        ]
        ssh_dir = self.home / ".ssh"
        public_keys: list[str] = []
        if ssh_dir.is_dir():
            public_keys.extend(sorted(path.name for path in ssh_dir.glob("*.pub")))
        return TerminalStatus(
            os.getuid(),
            os.getgid(),
            tuple(groups),
            str(self.home),
            str(self.workspace_root),
            self.settings.shell,
            self.workspace_list().count,
            job_states,
            DiskUsage(usage.total, usage.used, usage.free),
            {name: shutil.which(name, path=self.settings.path) or "" for name in tool_names},
            tuple(serial_devices),
            tuple(public_keys),
            (self.home / ".gitconfig").is_file(),
        )

    def _job_public(self, job: JobT) -> JobStatus:
        try:
            log_fd = self._open_owned_job_file(job.log_path.parent, "output.log", os.O_RDONLY)
            try:
                output_bytes = os.fstat(log_fd).st_size
            finally:
                os.close(log_fd)
        except FileNotFoundError:
            output_bytes = 0
        return JobStatus(
            job.job_id,
            job.workspace_id,
            job.label,
            job.command,
            job.cwd,
            job.interactive,
            job.state,
            job.pid,
            job.exit_code,
            job.signal_number,
            _timestamp(job.created_at),
            _timestamp(job.started_at),
            _timestamp(job.ended_at),
            round((job.ended_at or time.time()) - job.started_at, 3),
            output_bytes,
            job.log_truncated,
            job.timeout_seconds,
        )

    def job_status(self, job_id: str) -> JobStatus:
        return self._job_public(self._get_job(job_id))

    def job_list(
        self, workspace_id: str = "", state: str = "", offset: int = 0, limit: int = 100
    ) -> JobList:
        workspace = workspace_id.strip()
        if workspace:
            self._require_workspace(workspace)
        JobPage(offset, limit)
        state_filter = state.strip()
        matched = [
            job
            for job in sorted(self._jobs.values(), key=lambda item: item.created_at, reverse=True)
            if self._job_visible(job.job_id)
            and (not workspace or job.workspace_id == workspace)
            and (not state_filter or job.state == state_filter)
        ]
        selected: list[JobStatus] = [
            self._job_public(job) for job in matched[offset : offset + limit]
        ]
        return JobList(
            tuple(selected),
            len(selected),
            len(matched),
            offset,
            limit,
            offset + len(selected) < len(matched),
        )

    def job_delete(self, job_id: str, *, reason: str = "explicit_job_delete") -> JobDeleted:
        job = self._get_job(job_id)
        if (
            job.state in {"running", "cancelling"}
            or (job.watcher_task is not None and (not job.watcher_task.done()))
            or (job.reader_task is not None and (not job.reader_task.done()))
        ):
            self._logger.info(
                "job cleanup skipped job_id=%s workspace_id=%s reason=active_job state=%s",
                job.job_id,
                job.workspace_id,
                job.state,
            )
            raise TerminalError("running jobs must be cancelled before deletion")
        size_bytes = self._tree_size_bytes(job.metadata_path.parent)
        with suppress(FileNotFoundError):
            shutil.rmtree(job.metadata_path.parent)
        self._jobs.pop(job.job_id, None)
        self._logger.info(
            "job cleanup deleted job_id=%s workspace_id=%s reason=%s state=%s freed_bytes=%d",
            job.job_id,
            job.workspace_id,
            reason,
            job.state,
            size_bytes,
        )
        return JobDeleted(job.job_id, True, reason, size_bytes)

    def job_cleanup(
        self, older_than_hours: int = 168, dry_run: bool = True, limit: int = 1000
    ) -> JobCleanup:
        RetentionPolicy(older_than_hours, limit)
        cutoff = time.time() - older_than_hours * 3600
        self._logger.info(
            "job cleanup scan started older_than_hours=%d dry_run=%s limit=%d retained_jobs=%d",
            older_than_hours,
            dry_run,
            limit,
            len(self._jobs),
        )
        candidates = [
            job
            for job in sorted(
                self._jobs.values(), key=lambda item: item.ended_at or item.created_at
            )
            if self._job_visible(job.job_id)
            and job.state not in {"running", "cancelling"}
            and (job.ended_at or job.created_at) <= cutoff
        ][:limit]
        ids = [job.job_id for job in candidates]
        candidate_bytes = sum(self._tree_size_bytes(job.metadata_path.parent) for job in candidates)
        for job in candidates:
            age_hours = max(0.0, (time.time() - (job.ended_at or job.created_at)) / 3600)
            self._logger.info(
                "job cleanup candidate job_id=%s workspace_id=%s "
                "reason=retention_expired state=%s age_hours=%.2f dry_run=%s",
                job.job_id,
                job.workspace_id,
                job.state,
                age_hours,
                dry_run,
            )
        freed_bytes = 0
        if not dry_run:
            for job_id in ids:
                result = self.job_delete(job_id, reason="retention_expired")
                freed_bytes += result.freed_bytes
        self._logger.info(
            "job cleanup scan completed candidates=%d candidate_bytes=%d "
            "deleted=%d freed_bytes=%d dry_run=%s",
            len(ids),
            candidate_bytes,
            0 if dry_run else len(ids),
            freed_bytes,
            dry_run,
        )
        public_ids: list[str] = []
        public_ids.extend(ids)
        return JobCleanup(
            dry_run,
            older_than_hours,
            tuple(public_ids),
            len(ids),
            candidate_bytes,
            freed_bytes,
            "retention_expired",
        )

    async def job_read(
        self, job_id: str, cursor: int = 0, max_bytes: int | None = None, wait_seconds: float = 0
    ) -> JobRead:
        job = self._get_job(job_id)
        if cursor < 0:
            raise TerminalError("cursor must be >= 0")
        requested_limit = max_bytes or self.settings.max_job_read_bytes
        if requested_limit <= 0:
            raise TerminalError("max_bytes must be > 0")
        limit = min(requested_limit, self.settings.max_job_read_bytes)
        if not math.isfinite(wait_seconds) or wait_seconds < 0:
            raise TerminalError("wait_seconds must be finite and nonnegative")
        deadline = time.monotonic() + min(wait_seconds, 30)
        while True:
            try:
                fd = self._open_owned_job_file(job.log_path.parent, "output.log", os.O_RDONLY)
                try:
                    size = os.fstat(fd).st_size
                finally:
                    os.close(fd)
            except FileNotFoundError:
                size = 0
            if size > cursor or job.state not in {"running", "cancelling"}:
                break
            if time.monotonic() >= deadline:
                break
            await asyncio.sleep(0.05)
        if cursor > size:
            raise TerminalError(f"cursor {cursor} is beyond retained output size {size}")
        with os.fdopen(
            self._open_owned_job_file(job.log_path.parent, "output.log", os.O_RDONLY), "rb"
        ) as stream:
            stream.seek(cursor)
            data = stream.read(limit)
        next_cursor = cursor + len(data)
        return JobRead(
            job.job_id,
            cursor,
            next_cursor,
            data.decode("utf-8", errors="replace"),
            size,
            job.state,
            job.state not in {"running", "cancelling"} and next_cursor >= size,
            job.log_truncated,
        )

    def job_write(self, job_id: str, data: str) -> JobWrite:
        job = self._get_job(job_id)
        if not job.interactive:
            raise TerminalError("job is not interactive")
        if job.state != "running" or job.master_fd is None:
            raise TerminalError(f"interactive job is not running: {job.state}")
        payload = data.encode("utf-8")
        if len(payload) > min(self.settings.max_job_read_bytes, 1024 * 1024):
            raise TerminalError("interactive input exceeds the bounded PTY write limit")
        try:
            written = os.write(job.master_fd, payload)
        except BlockingIOError:
            written = 0
        return JobWrite(job.job_id, written, written < len(payload))

    def job_resize(self, job_id: str, cols: int, rows: int) -> JobResize:
        job = self._get_job(job_id)
        if not job.interactive:
            raise TerminalError("job is not interactive")
        if job.master_fd is None:
            raise TerminalError("interactive job is not running")
        self._resize_fd(job.master_fd, cols, rows)
        return JobResize(job.job_id, cols, rows)

    async def job_wait(self, job_id: str, timeout_seconds: float = 30) -> JobStatus:
        job = self._get_job(job_id)
        if not math.isfinite(timeout_seconds) or timeout_seconds < 0:
            raise TerminalError("timeout_seconds must be finite and nonnegative")
        if job.watcher_task is not None and job.state in {"running", "cancelling"}:
            with suppress(TimeoutError):
                await asyncio.wait_for(
                    asyncio.shield(job.watcher_task), timeout=min(timeout_seconds, 300)
                )
        return self._job_public(job)

    async def job_cancel(self, job_id: str, grace_seconds: float = 3) -> JobStatus:
        job = self._get_job(job_id)
        if not math.isfinite(grace_seconds) or grace_seconds <= 0:
            raise TerminalError("grace_seconds must be finite and positive")
        async with job.cancel_lock:
            process = job.process
            if process is None or job.state not in {"running", "cancelling"}:
                return self._job_public(job)
            if job.state == "running":
                job.state = "cancelling"
                self._persist(job)
            if process.returncode is None:
                self._signal_process_group(process.pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(
                    asyncio.shield(process.wait()), timeout=max(0.1, min(grace_seconds, 30))
                )
            except TimeoutError:
                if process.returncode is None:
                    self._signal_process_group(process.pid, signal.SIGKILL)
                await process.wait()
        if job.watcher_task is not None:
            with suppress(TimeoutError):
                await asyncio.wait_for(asyncio.shield(job.watcher_task), timeout=2)
        return self._job_public(job)
