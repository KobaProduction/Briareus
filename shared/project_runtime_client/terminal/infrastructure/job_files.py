"""Owner-confined atomic job metadata and restart recovery adapter.

Saved metadata cannot confer PID ownership. Recovery never replays or signals it.
"""

from __future__ import annotations

import json
import os
import re
import stat
import time
import uuid
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import asdict
from pathlib import Path

from project_runtime_client.terminal.domain.policy import TerminalError, WorkspaceIdentity

from .job_contract import JobFactory, JobState
from .job_metadata import RecoveredJobMetadata, SavedJobMetadata


class JobFileRepository[JobT: JobState]:
    def __init__(self, jobs_root: Path, job_factory: JobFactory[JobT, float]) -> None:
        self.jobs_root = jobs_root
        self.job_factory = job_factory

    @staticmethod
    def _open_owned_job_file(folder: Path, name: str, flags: int) -> int:
        """Pin one regular job file beneath a non-symlink owner directory."""
        if name not in {"metadata.json", "output.log"}:
            raise TerminalError("job file name is not recognized")
        directory = os.open(folder, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
        try:
            owner = os.fstat(directory)
            if owner.st_uid != os.geteuid() or not stat.S_ISDIR(owner.st_mode):
                raise TerminalError("job metadata directory owner invalid")
            fd = os.open(name, flags | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=directory)
            try:
                info = os.fstat(fd)
                if (
                    not stat.S_ISREG(info.st_mode)
                    or info.st_uid != owner.st_uid
                    or info.st_dev != owner.st_dev
                    or (info.st_nlink != 1)
                ):
                    raise TerminalError("job log/metadata file owner invalid")
            except BaseException:
                os.close(fd)
                raise
            return fd
        finally:
            os.close(directory)

    def _persist(self, job: JobT) -> None:
        job.metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata = SavedJobMetadata.from_job(job)
        folder_fd = os.open(
            job.metadata_path.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
        )
        temporary = f".metadata-{uuid.uuid4().hex}.tmp"
        try:
            if os.fstat(folder_fd).st_uid != os.geteuid():
                raise TerminalError("job metadata owner invalid")
            temporary_fd = os.open(
                temporary,
                os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW | os.O_CLOEXEC,
                0o600,
                dir_fd=folder_fd,
            )
            try:
                with os.fdopen(temporary_fd, "wb") as stream:
                    stream.write(
                        json.dumps(asdict(metadata), ensure_ascii=False, indent=2).encode()
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, "metadata.json", src_dir_fd=folder_fd, dst_dir_fd=folder_fd)
                os.fsync(folder_fd)
            finally:
                with suppress(FileNotFoundError):
                    os.unlink(temporary, dir_fd=folder_fd)
        finally:
            os.close(folder_fd)

    def recover(self) -> Iterator[JobT]:
        for metadata_path in sorted(self.jobs_root.glob("*/metadata.json")):
            try:
                folder = metadata_path.parent
                if (
                    metadata_path.is_symlink()
                    or folder.is_symlink()
                    or (not re.fullmatch("[0-9a-f]{32}", folder.name))
                ):
                    continue
                log_path = folder / "output.log"
                try:
                    owned_log_fd = self._open_owned_job_file(folder, "output.log", os.O_RDONLY)
                    os.close(owned_log_fd)
                    metadata_fd = self._open_owned_job_file(folder, "metadata.json", os.O_RDONLY)
                    with os.fdopen(metadata_fd, "r", encoding="utf-8") as input_file:
                        if os.fstat(input_file.fileno()).st_size > 1024 * 1024:
                            continue
                        metadata = RecoveredJobMetadata.decode(input_file.read())
                except (OSError, TerminalError):
                    continue
                if metadata.job_id != folder.name:
                    continue
                workspace_id = WorkspaceIdentity(metadata.workspace_id).value
                state = metadata.state
                ended_at = metadata.ended_at
                if state in {"running", "cancelling"}:
                    state = "interrupted"
                    ended_at = time.time()
                job = self.job_factory(
                    job_id=folder.name,
                    workspace_id=workspace_id,
                    command=metadata.command,
                    cwd=metadata.cwd,
                    interactive=metadata.interactive,
                    label=metadata.label,
                    state=state,
                    created_at=metadata.created_at,
                    started_at=metadata.started_at,
                    ended_at=ended_at,
                    exit_code=metadata.exit_code,
                    signal_number=metadata.signal_number,
                    pid=None,
                    log_path=log_path,
                    metadata_path=metadata_path,
                    log_truncated=metadata.log_truncated,
                    timeout_seconds=metadata.timeout_seconds,
                )
                yield job
            except (
                OSError,
                ValueError,
                KeyError,
                TypeError,
                OverflowError,
                TerminalError,
                json.JSONDecodeError,
            ):
                continue
