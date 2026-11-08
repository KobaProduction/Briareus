from __future__ import annotations

import asyncio

from briareus_json_values import JsonObject, JsonValue, json_loads, json_value
from briareus_mcp_client.mcp_client_pool import PersistentMcpClientPool
from fastmcp import Client
from fastmcp.client.client import CallToolResult

from control_panel_api.domain.admin_data.terminal import (
    JobCleanup,
    JobDeletion,
    JobList,
    JobTail,
    TerminalJob,
    TerminalOverview,
    TerminalStatus,
    WorkspaceDeletion,
    WorkspaceList,
)

_DEFAULT_TERMINAL_MCP_URL = "http://server-mcp-hand:8000/mcp"


def _decode_result(value: object) -> JsonValue:
    current: object = value
    for _ in range(8):
        if isinstance(current, dict):
            if "result" in current:
                current = current["result"]
                continue
            if "data" in current:
                current = current["data"]
                continue
            return json_value(current, context="terminal admin result")
        if isinstance(current, str):
            try:
                current = json_loads(current, context="terminal admin result")
            except ValueError:
                return current
            continue
        return json_value(current, context="terminal admin result")
    return json_value(current, context="terminal admin result")


def _decode_call_result(result: CallToolResult) -> JsonValue | None:
    candidates: list[object | None] = [result.structured_content, result.data]
    candidates.extend(block.text for block in result.content if block.type == "text")
    for candidate in candidates:
        if candidate is not None:
            return _decode_result(candidate)
    return None


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
            lambda: Client(self.url, timeout=self.timeout_seconds),
            name="control-panel-terminal",
            size=3,
        )

    async def _call(self, tool: str, arguments: JsonObject | None = None) -> JsonValue:
        result = await self._pool.call_tool(
            tool,
            arguments or {},
            timeout_seconds=self.timeout_seconds,
        )
        decoded = _decode_call_result(result)
        if decoded is None:
            raise RuntimeError(f"{tool} returned no result")
        if isinstance(decoded, dict):
            error = decoded.get("error")
            if isinstance(error, str) and error.strip():
                raise RuntimeError(error)
        return decoded

    async def overview(self) -> TerminalOverview:
        status_raw, workspaces_raw, jobs_raw = await asyncio.gather(
            self._call("terminal_status"),
            self._call("workspace_list"),
            self._call("job_list"),
        )
        return TerminalOverview(
            status=TerminalStatus.model_validate(status_raw),
            workspaces=WorkspaceList.model_validate(workspaces_raw).workspaces,
            jobs=JobList.model_validate(jobs_raw).jobs,
        )

    async def job_status(self, job_id: str) -> TerminalJob:
        return TerminalJob.model_validate(
            await self._call("job_status", {"job_id": job_id}),
        )

    async def job_tail(self, job_id: str, max_bytes: int = 16 * 1024) -> JobTail:
        status = await self.job_status(job_id)
        size = status.output_bytes
        cursor = max(0, size - max_bytes)
        return JobTail.model_validate(
            await self._call(
                "job_read",
                {
                    "job_id": job_id,
                    "cursor": cursor,
                    "max_bytes": max_bytes,
                    "wait_seconds": 0,
                },
            ),
        )

    async def cancel_job(self, job_id: str) -> TerminalJob:
        return TerminalJob.model_validate(
            await self._call(
                "job_cancel",
                {"job_id": job_id, "grace_seconds": 2},
            ),
        )

    async def delete_job(self, job_id: str) -> JobDeletion:
        return JobDeletion.model_validate(
            await self._call("job_delete", {"job_id": job_id}),
        )

    async def cleanup_jobs(
        self,
        older_than_hours: int = 168,
        dry_run: bool = False,
    ) -> JobCleanup:
        return JobCleanup.model_validate(
            await self._call(
                "job_cleanup",
                {
                    "older_than_hours": older_than_hours,
                    "dry_run": dry_run,
                    "limit": 1000,
                },
            ),
        )

    async def delete_workspace(self, workspace_id: str) -> WorkspaceDeletion:
        return WorkspaceDeletion.model_validate(
            await self._call(
                "workspace_delete",
                {"workspace_id": workspace_id, "force": False},
            ),
        )
