from __future__ import annotations

from typing import TYPE_CHECKING, Annotated

from pydantic import Field

if TYPE_CHECKING:
    from mcp.types import ToolAnnotations
from dataclasses import dataclass

from project_runtime_client.terminal.tool_annotations import _TerminalAnnotations
from runtime_peer.terminal_receipts import (
    JobCleanup,
    JobDeleted,
    JobExecution,
    JobList,
    JobRead,
    JobResize,
    JobStatus,
    JobWrite,
    TerminalStatus,
    WorkspaceCreated,
    WorkspaceDeleted,
    WorkspaceInfo,
    WorkspaceList,
)

from .manager import TerminalError, TerminalManager
from .tool_registry import TerminalRegistry


def _execution_manager(manager: TerminalManager | None) -> TerminalManager:
    if manager is None:
        raise TerminalError("Terminal metadata registration has no execution authority")
    return manager


def register_terminal_tools(
    mcp: TerminalRegistry, manager: TerminalManager | None, *, include_metadata: bool = True
) -> None:
    labels = _annotations(include_metadata)
    _register_workspaces(mcp, manager, labels)
    _register_execution(mcp, manager, labels)
    _register_jobs(mcp, manager, labels)


def _register_workspaces(
    mcp: TerminalRegistry, manager: TerminalManager | None, labels: TerminalAnnotations
) -> None:

    @mcp.tool(title="Terminal status", annotations=labels.readonly)
    def terminal_status() -> TerminalStatus:
        """Report terminal runtime, workspace, job and toolchain status."""
        return _execution_manager(manager).status()

    @mcp.tool(title="Workspace list", annotations=labels.readonly)
    def workspace_list() -> WorkspaceList:
        """List persistent terminal workspaces."""
        return _execution_manager(manager).workspace_list()

    @mcp.tool(title="Workspace create", annotations=labels.write)
    def workspace_create(workspace_id: str) -> WorkspaceCreated:
        """Create a persistent workspace directory."""
        return _execution_manager(manager).workspace_create(workspace_id)

    @mcp.tool(title="Workspace info", annotations=labels.readonly)
    def workspace_info(workspace_id: str) -> WorkspaceInfo:
        """Inspect one workspace and its jobs."""
        return _execution_manager(manager).workspace_info(workspace_id)

    @mcp.tool(
        title="Workspace delete",
        annotations=labels.destructive,
    )
    async def workspace_delete(workspace_id: str, force: bool = False) -> WorkspaceDeleted:
        """Delete a workspace. Active jobs block deletion unless force=true."""
        return await _execution_manager(manager).workspace_delete(workspace_id, force=force)


def _register_execution(
    mcp: TerminalRegistry, manager: TerminalManager | None, labels: TerminalAnnotations
) -> None:

    @mcp.tool(title="Terminal exec", annotations=labels.external)
    async def terminal_exec(
        workspace_id: str,
        command: str,
        cwd: str = "",
        env: dict[str, str] | None = None,
        timeout_seconds: float | None = None,
        max_output_bytes: int | None = None,
    ) -> JobExecution:
        """Start a command once and return its job_id, state and initial combined output.

        Execution has no default time limit; Node/server policy or an explicit
        timeout_seconds may limit it. A running command continues as a retained
        job: call job_read from next_cursor or job_status with current rights.
        The brief initial observation never terminates a long command. Never
        repeat an uncertain start; inspect the known job/operation instead.
        """
        return await _execution_manager(manager).terminal_exec(
            workspace_id,
            command,
            cwd=cwd,
            env=env,
            timeout_seconds=timeout_seconds,
            max_output_bytes=max_output_bytes,
        )

    @mcp.tool(title="Job start", annotations=labels.external)
    async def job_start(
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
        """Start a persistent long-running or interactive process job."""
        return await _execution_manager(manager).job_start(
            workspace_id,
            command,
            cwd=cwd,
            env=env,
            interactive=interactive,
            label=label,
            cols=cols,
            rows=rows,
            timeout_seconds=timeout_seconds,
        )


def _register_jobs(
    mcp: TerminalRegistry, manager: TerminalManager | None, labels: TerminalAnnotations
) -> None:

    @mcp.tool(title="Job status", annotations=labels.readonly)
    def job_status(job_id: str) -> JobStatus:
        """Read one job's process state and metadata."""
        return _execution_manager(manager).job_status(job_id)

    @mcp.tool(title="Job list", annotations=labels.readonly)
    def job_list(
        workspace_id: str = "", state: str = "", offset: int = 0, limit: int = 100
    ) -> JobList:
        """List jobs with optional workspace/state filters and pagination."""
        return _execution_manager(manager).job_list(
            workspace_id=workspace_id, state=state, offset=offset, limit=limit
        )

    @mcp.tool(title="Job delete", annotations=labels.destructive)
    def job_delete(job_id: str) -> JobDeleted:
        """Delete retained metadata/logs for a completed job."""
        return _execution_manager(manager).job_delete(job_id)

    @mcp.tool(title="Job cleanup", annotations=labels.destructive)
    def job_cleanup(
        older_than_hours: int = 168, dry_run: bool = True, limit: int = 1000
    ) -> JobCleanup:
        """Preview or remove completed job logs older than a retention threshold."""
        return _execution_manager(manager).job_cleanup(
            older_than_hours=older_than_hours, dry_run=dry_run, limit=limit
        )

    @mcp.tool(title="Job read", annotations=labels.readonly)
    async def job_read(
        job_id: str, cursor: int = 0, max_bytes: int | None = None, wait_seconds: float = 0
    ) -> JobRead:
        """Read only job output appended after cursor and return next_cursor."""
        return await _execution_manager(manager).job_read(
            job_id, cursor=cursor, max_bytes=max_bytes, wait_seconds=wait_seconds
        )

    @mcp.tool(title="Job write", annotations=labels.external)
    def job_write(job_id: str, data: str) -> JobWrite:
        """Write input to a running interactive PTY job."""
        return _execution_manager(manager).job_write(job_id, data)

    @mcp.tool(title="Job resize", annotations=labels.write)
    def job_resize(job_id: str, cols: int, rows: int) -> JobResize:
        """Resize a running interactive PTY job."""
        return _execution_manager(manager).job_resize(job_id, cols, rows)

    @mcp.tool(title="Job wait", annotations=labels.readonly)
    async def job_wait(job_id: str, timeout_seconds: float = 3) -> JobStatus:
        """Wait up to timeout_seconds for a job, then return current state."""
        return await _execution_manager(manager).job_wait(job_id, timeout_seconds=timeout_seconds)

    @mcp.tool(title="Job cancel", annotations=labels.destructive)
    async def job_cancel(
        job_id: str, grace_seconds: Annotated[float, Field(gt=0, le=3)] = 3
    ) -> JobStatus:
        """Terminate a running job process group; grace_seconds must be >0 and <=3.

        Use 0.5 for a short grace period. Zero is invalid. Cancellation retains
        job metadata/logs; use job_delete after the job has stopped to remove them.
        """
        return await _execution_manager(manager).job_cancel(job_id, grace_seconds=grace_seconds)


@dataclass(frozen=True, slots=True)
class TerminalAnnotations:
    external: ToolAnnotations | None
    destructive: ToolAnnotations | None
    readonly: ToolAnnotations | None
    write: ToolAnnotations | None


_annotations = _TerminalAnnotations(TerminalAnnotations)
