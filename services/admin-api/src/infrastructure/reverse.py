from __future__ import annotations

import posixpath

from application.analysis_views import (
    AnalysisCoverage,
    AnalysisOpenProgram,
    AnalysisOpenPrograms,
    AnalysisOverview,
    AnalysisProjectDeleted,
    AnalysisProjectFiles,
    AnalysisProjectOpened,
    AnalysisProjectReleased,
    AnalysisProjectSession,
    AnalysisSessionSettings,
    AnalysisWorkerChanged,
    AnalysisWorkerQueueCleared,
    AnalysisWorkerRecovered,
)
from domain.analysis import FunctionDocumentation, assess_coverage, select_coverage
from fastmcp import Client
from fastmcp.client.transports import ClientTransport
from mcp.types import CallToolRequestParams
from pydantic import BaseModel

from common.mcp_client_pool import PersistentMcpClientPool
from common.mcp_replies import decode_mcp_reply

from . import analysis_commands as commands
from .analysis_measurements import FunctionCount, FunctionListing, FunctionQualityBatch

_DEFAULT_GHIDRA_MCP_URL = "http://ghidra:8000/mcp"


class ReverseAdminClient:
    """Read/control project worker state through the private Ghidra MCP service."""

    def __init__(
        self,
        url: str = _DEFAULT_GHIDRA_MCP_URL,
        *,
        timeout_seconds: float = 180.0,
    ) -> None:
        self.url = url
        self.timeout_seconds = timeout_seconds
        self._pool = PersistentMcpClientPool(
            lambda: Client[ClientTransport](self.url, timeout=self.timeout_seconds),
            name="admin-api-reverse",
            size=3,
        )

    async def _call[T: BaseModel](
        self, command: commands.AnalysisCommand, response_type: type[T]
    ) -> T:
        result = await self._pool.call_tool(
            CallToolRequestParams(
                name=command.tool_name, arguments=command.model_dump(mode="json")
            ),
            timeout_seconds=self.timeout_seconds,
        )
        return decode_mcp_reply(result, response_type, context=f"reverse admin {command.tool_name}")

    async def overview(self) -> AnalysisOverview:
        overview = await self._call(commands.ListProjects(), AnalysisOverview)
        worker_by_project = {
            worker.project_id: worker.worker_index
            for worker in overview.workers
            if worker.project_id is not None
        }
        for project in overview.projects:
            project.worker_index = worker_by_project.get(project.project_id)
            parent = posixpath.dirname(project.path)
            if parent in {"", "/", "/projects"}:
                project.group = "Root"
            elif parent.startswith("/projects/"):
                project.group = parent[len("/projects/") :]
            else:
                project.group = parent
        overview.projects.sort(
            key=lambda project: ((project.group or "").casefold(), project.name.casefold())
        )
        return overview

    async def session_info(self, project_id: str) -> AnalysisProjectSession:
        return await self._call(
            commands.ProjectSessionInfo(project_id=project_id), AnalysisProjectSession
        )

    async def open_session(self, project_id: str) -> AnalysisProjectOpened:
        return await self._call(commands.OpenProject(project_id=project_id), AnalysisProjectOpened)

    async def release_session(self, project_id: str) -> AnalysisProjectReleased:
        return await self._call(
            commands.ReleaseProject(project_id=project_id), AnalysisProjectReleased
        )

    async def project_files(self, project_id: str, folder: str = "/") -> AnalysisProjectFiles:
        return await self._call(
            commands.ProjectFiles(project_id=project_id, folder=folder), AnalysisProjectFiles
        )

    async def open_programs(self, project_id: str) -> list[AnalysisOpenProgram]:
        result = await self._call(
            commands.OpenPrograms(project_id=project_id), AnalysisOpenPrograms
        )
        return result.programs

    async def create_project(self, name: str, parent_dir: str = "") -> AnalysisProjectOpened:
        return await self._call(
            commands.CreateProject(name=name, parent_dir=parent_dir), AnalysisProjectOpened
        )

    async def delete_project(self, project_id: str) -> AnalysisProjectDeleted:
        return await self._call(
            commands.DeleteProject(project_id=project_id), AnalysisProjectDeleted
        )

    async def set_worker_enabled(
        self,
        worker_index: int,
        enabled: bool,
    ) -> AnalysisWorkerChanged:
        return await self._call(
            commands.SetWorkerEnabled(
                worker_index=worker_index, enabled=enabled, close_project=not enabled
            ),
            AnalysisWorkerChanged,
        )

    async def clear_worker_queue(self, worker_index: int) -> AnalysisWorkerQueueCleared:
        return await self._call(
            commands.ClearWorkerQueue(worker_index=worker_index), AnalysisWorkerQueueCleared
        )

    async def recover_worker(
        self,
        worker_index: int,
        *,
        timeout_seconds: float = 4.0,
    ) -> AnalysisWorkerRecovered:
        return await self._call(
            commands.RecoverWorker(worker_index=worker_index, timeout_seconds=timeout_seconds),
            AnalysisWorkerRecovered,
        )

    async def coverage(
        self,
        project_id: str,
        program: str,
        *,
        full: bool = False,
        sample_size: int = 50,
        batch_size: int = 20,
    ) -> AnalysisCoverage:
        count = await self._call(
            commands.FunctionCount(project_id=project_id, program=program), FunctionCount
        )
        listing = await self._call(
            commands.ListFunctions(
                project_id=project_id, program=program, limit=max(count.function_count, 10000)
            ),
            FunctionListing,
        )
        addresses = [item.address for item in listing.functions if item.address]
        total_functions = max(count.function_count, len(addresses))

        selection = select_coverage(addresses, full=full, sample_size=sample_size)
        selected = selection.addresses

        results: list[FunctionDocumentation] = []
        for start in range(0, len(selected), max(1, batch_size)):
            batch = selected[start : start + max(1, batch_size)]
            payload = await self._call(
                commands.FunctionCompleteness(
                    project_id=project_id, program=program, addresses=",".join(batch)
                ),
                FunctionQualityBatch,
            )
            results.extend(payload.results)

        return AnalysisCoverage(
            root=assess_coverage(
                project_id,
                program,
                total_functions=total_functions,
                selection=selection,
                results=results,
            )
        )

    async def session_settings(self) -> AnalysisSessionSettings:
        return await self._call(commands.SessionSettings(), AnalysisSessionSettings)

    async def set_idle_timeout(self, idle_timeout_seconds: float) -> AnalysisSessionSettings:
        return await self._call(
            commands.SetIdleTimeout(idle_timeout_seconds=idle_timeout_seconds),
            AnalysisSessionSettings,
        )
