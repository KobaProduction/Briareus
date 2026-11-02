from __future__ import annotations

import asyncio

from application.terminal_views import (
    JobCleanup,
    JobDeleted,
    JobRead,
    JobStatus,
    TerminalJobs,
    TerminalOverview,
    TerminalStatus,
    TerminalWorkspaces,
    WorkspaceDeleted,
)
from fastmcp import Client
from fastmcp.client.transports import ClientTransport
from mcp.types import CallToolRequestParams
from pydantic import BaseModel

from common.mcp_client_pool import PersistentMcpClientPool
from common.mcp_replies import decode_mcp_reply

from .terminal_commands import CancelJob, CleanupJobs, DeleteWorkspace, JobSelection, ReadJob

_DEFAULT_TERMINAL_MCP_URL = "http://terminal:8000/mcp"


class TerminalAdminClient:
    def __init__(
        self,
        url: str = _DEFAULT_TERMINAL_MCP_URL,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._pool = PersistentMcpClientPool(
            lambda: Client[ClientTransport](self.url, timeout=self.timeout_seconds),
            name="admin-api-terminal",
            size=3,
        )

    async def _call[T: BaseModel](
        self, tool: str, arguments: BaseModel | None = None, *, response_type: type[T]
    ) -> T:
        result = await self._pool.call_tool(
            CallToolRequestParams(
                name=tool,
                arguments=arguments.model_dump(mode="json") if arguments is not None else {},
            ),
            timeout_seconds=self.timeout_seconds,
        )
        return decode_mcp_reply(result, response_type, context=f"terminal admin {tool}")

    async def overview(self) -> TerminalOverview:
        status_raw, workspaces_raw, jobs_raw = await asyncio.gather(
            self._call("terminal_status", response_type=TerminalStatus),
            self._call("workspace_list", response_type=TerminalWorkspaces),
            self._call("job_list", response_type=TerminalJobs),
        )
        return TerminalOverview(
            status=status_raw, workspaces=workspaces_raw.workspaces, jobs=jobs_raw.jobs
        )

    async def job_status(self, job_id: str) -> JobStatus:
        return await self._call("job_status", JobSelection(job_id=job_id), response_type=JobStatus)

    async def job_tail(self, job_id: str, max_bytes: int = 16 * 1024) -> JobRead:
        status = await self.job_status(job_id)
        size = status.output_bytes
        cursor = max(0, size - max_bytes)
        return await self._call(
            "job_read",
            ReadJob(job_id=job_id, cursor=cursor, max_bytes=max_bytes),
            response_type=JobRead,
        )

    async def cancel_job(self, job_id: str) -> JobStatus:
        return await self._call("job_cancel", CancelJob(job_id=job_id), response_type=JobStatus)

    async def delete_job(self, job_id: str) -> JobDeleted:
        return await self._call("job_delete", JobSelection(job_id=job_id), response_type=JobDeleted)

    async def cleanup_jobs(
        self,
        older_than_hours: int = 168,
        dry_run: bool = False,
    ) -> JobCleanup:
        return await self._call(
            "job_cleanup",
            CleanupJobs(older_than_hours=older_than_hours, dry_run=dry_run),
            response_type=JobCleanup,
        )

    async def delete_workspace(self, workspace_id: str) -> WorkspaceDeleted:
        return await self._call(
            "workspace_delete",
            DeleteWorkspace(workspace_id=workspace_id),
            response_type=WorkspaceDeleted,
        )
