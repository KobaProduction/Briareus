from __future__ import annotations

from pathlib import Path
from typing import BinaryIO, Protocol

from briareus_json_values import JsonObject, JsonValue

from control_panel_api.domain.admin_data.analysis import (
    AnalysisOverview,
    AnalysisSession,
    CoverageResult,
)
from control_panel_api.domain.admin_data.files import (
    FileDeletion,
    FileEntry,
    FileListing,
    FileStats,
    FileStatus,
)
from control_panel_api.domain.admin_data.terminal import (
    JobCleanup,
    JobDeletion,
    JobTail,
    TerminalJob,
    TerminalOverview,
    WorkspaceDeletion,
)


class FileAdminPort(Protocol):
    def list(self, path: str = "", *, offset: int = 0, limit: int = 500) -> FileListing: ...

    def status(self) -> FileStatus: ...

    def stats(self) -> FileStats: ...

    def info(self, path: str) -> FileEntry: ...

    def upload(
        self, stream: BinaryIO, *, destination: str, overwrite: bool = False
    ) -> FileEntry: ...

    def path_for(self, path: str) -> Path: ...

    def mkdir(self, path: str) -> FileEntry: ...

    def delete(self, path: str, *, recursive: bool = False) -> FileDeletion: ...


class TerminalAdminPort(Protocol):
    async def overview(self) -> TerminalOverview: ...

    async def job_status(self, job_id: str) -> TerminalJob: ...

    async def job_tail(self, job_id: str, max_bytes: int = 16 * 1024) -> JobTail: ...

    async def cancel_job(self, job_id: str) -> TerminalJob: ...

    async def delete_job(self, job_id: str) -> JobDeletion: ...

    async def cleanup_jobs(
        self, older_than_hours: int = 168, dry_run: bool = False
    ) -> JobCleanup: ...

    async def delete_workspace(self, workspace_id: str) -> WorkspaceDeletion: ...


class AnalysisAdminPort(Protocol):
    async def overview(self) -> AnalysisOverview: ...

    async def session_info(self, project_id: str) -> AnalysisSession: ...

    async def open_session(self, project_id: str) -> JsonObject: ...

    async def release_session(self, project_id: str) -> JsonObject: ...

    async def project_files(self, project_id: str, folder: str = "/") -> JsonObject: ...

    async def open_programs(self, project_id: str) -> list[JsonValue]: ...

    async def create_project(self, name: str, parent_dir: str = "") -> JsonObject: ...

    async def delete_project(self, project_id: str) -> JsonObject: ...

    async def set_worker_enabled(self, worker_index: int, enabled: bool) -> JsonObject: ...

    async def worker_heap_settings(self, worker_index: int) -> JsonObject: ...

    async def set_worker_heap(self, worker_index: int, heap_mb: int) -> JsonObject: ...

    async def hard_stop_worker(self, worker_index: int) -> JsonObject: ...

    async def start_worker(self, worker_index: int) -> JsonObject: ...

    async def clear_worker_queue(self, worker_index: int) -> JsonObject: ...

    async def recover_worker(
        self, worker_index: int, *, timeout_seconds: float = 4.0
    ) -> JsonObject: ...

    async def coverage(
        self,
        project_id: str,
        program: str,
        *,
        full: bool = False,
        sample_size: int = 50,
        batch_size: int = 20,
    ) -> CoverageResult: ...

    async def session_settings(self) -> JsonObject: ...

    async def set_idle_timeout(self, idle_timeout_seconds: float) -> JsonObject: ...
