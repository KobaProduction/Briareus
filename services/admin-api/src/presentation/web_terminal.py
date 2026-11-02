"""Retained terminal HTTP adapters with focused dependencies."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from application.panel_views import (
    TerminalJobView,
)
from application.terminal_views import JobCleanup, JobDeleted, JobStatus, TerminalOverview
from application.terminal_views import WorkspaceDeleted as TerminalWorkspaceDeleted
from application.web_events import AdminWebEvents
from fastapi import APIRouter, Query, Request
from infrastructure.terminal import TerminalAdminClient

from presentation.web_admission import WebAdmission
from presentation.web_upstream_errors import web_upstream_errors


@dataclass(eq=False, repr=False)
class WebTerminalController:
    admission: WebAdmission
    terminal: TerminalAdminClient | None
    events: AdminWebEvents

    def mount(self, router: APIRouter) -> None:
        router.get("/terminal")(self.terminal_overview)
        router.get("/terminal/jobs/{job_id}")(self.terminal_job)
        router.post("/terminal/jobs/{job_id}/cancel")(self.terminal_cancel)
        router.delete("/terminal/jobs/{job_id}")(self.terminal_delete_job)
        router.post("/terminal/jobs/cleanup")(self.terminal_cleanup)
        router.delete("/terminal/workspaces/{workspace_id}")(self.terminal_delete_workspace)

    async def terminal_overview(self, request: Request) -> TerminalOverview:
        self.admission.require_user(request)
        with web_upstream_errors():
            return await self.admission.available(self.terminal).overview()

    async def terminal_job(self, job_id: str, request: Request) -> TerminalJobView:
        self.admission.require_user(request)
        with web_upstream_errors():
            job, tail = await asyncio.gather(
                self.admission.available(self.terminal).job_status(job_id),
                self.admission.available(self.terminal).job_tail(job_id),
            )
        return TerminalJobView(job=job, tail=tail)

    async def terminal_cancel(self, job_id: str, request: Request) -> JobStatus:
        api = self.admission.mutation(request, self.terminal)
        with web_upstream_errors():
            result = await api.cancel_job(job_id)
            await self.events.publish("terminal.job.cancelled", result)
            return result

    async def terminal_delete_job(self, job_id: str, request: Request) -> JobDeleted:
        api = self.admission.mutation(request, self.terminal)
        with web_upstream_errors():
            result = await api.delete_job(job_id)
            await self.events.publish("terminal.job.deleted", result)
            return result

    async def terminal_cleanup(
        self, request: Request, older_than_hours: int = Query(168, ge=0, le=87600)
    ) -> JobCleanup:
        api = self.admission.mutation(request, self.terminal)
        with web_upstream_errors():
            result = await api.cleanup_jobs(older_than_hours=older_than_hours, dry_run=False)
            await self.events.publish("terminal.jobs.cleaned", result)
            return result

    async def terminal_delete_workspace(
        self, workspace_id: str, request: Request
    ) -> TerminalWorkspaceDeleted:
        api = self.admission.mutation(request, self.terminal)
        with web_upstream_errors():
            result = await api.delete_workspace(workspace_id)
            await self.events.publish("terminal.workspace.deleted", result)
            return result
