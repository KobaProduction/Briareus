from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query, Request

from control_panel_api.domain.admin_data.terminal import (
    JobCleanup,
    JobDeletion,
    TerminalJob,
    TerminalJobView,
    TerminalOverview,
    WorkspaceDeletion,
)

from .context import WebApiContext


class TerminalRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/terminal", self.terminal_overview, methods=["GET"])
        router.add_api_route("/terminal/jobs/{job_id}", self.terminal_job, methods=["GET"])
        router.add_api_route(
            "/terminal/jobs/{job_id}/cancel", self.terminal_cancel, methods=["POST"]
        )
        router.add_api_route(
            "/terminal/jobs/{job_id}", self.terminal_delete_job, methods=["DELETE"]
        )
        router.add_api_route("/terminal/jobs/cleanup", self.terminal_cleanup, methods=["POST"])
        router.add_api_route(
            "/terminal/workspaces/{workspace_id}",
            self.terminal_delete_workspace,
            methods=["DELETE"],
        )

    async def terminal_overview(self, request: Request) -> TerminalOverview:
        self.context.require_user(request)
        try:
            return await self.context.available().terminal.overview()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def terminal_job(self, job_id: str, request: Request) -> TerminalJobView:
        self.context.require_user(request)
        try:
            job, tail = await asyncio.gather(
                self.context.available().terminal.job_status(job_id),
                self.context.available().terminal.job_tail(job_id),
            )
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return TerminalJobView(job=job, tail=tail)

    async def terminal_cancel(self, job_id: str, request: Request) -> TerminalJob:
        api = self.context.mutation(request)
        try:
            result = await api.terminal.cancel_job(job_id)
            await self.context.publish_management_event(api, "terminal.job.cancelled", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def terminal_delete_job(self, job_id: str, request: Request) -> JobDeletion:
        api = self.context.mutation(request)
        try:
            result = await api.terminal.delete_job(job_id)
            await self.context.publish_management_event(api, "terminal.job.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def terminal_cleanup(
        self, request: Request, older_than_hours: int = Query(168, ge=0, le=87600)
    ) -> JobCleanup:
        api = self.context.mutation(request)
        try:
            result = await api.terminal.cleanup_jobs(
                older_than_hours=older_than_hours, dry_run=False
            )
            await self.context.publish_management_event(api, "terminal.jobs.cleaned", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def terminal_delete_workspace(
        self, workspace_id: str, request: Request
    ) -> WorkspaceDeletion:
        api = self.context.mutation(request)
        try:
            result = await api.terminal.delete_workspace(workspace_id)
            await self.context.publish_management_event(api, "terminal.workspace.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
