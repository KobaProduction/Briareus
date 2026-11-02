"""Retained analysis HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.analysis_views import (
    AnalysisCoverage,
    AnalysisOpenProgram,
    AnalysisOverview,
    AnalysisProjectDeleted,
    AnalysisProjectFiles,
    AnalysisProjectOpened,
    AnalysisProjectReleased,
    AnalysisWorker,
    AnalysisWorkerChanged,
)
from application.panel_views import (
    AnalysisProjectView,
    AnalysisWorkers,
    InactiveAnalysisFiles,
    WorkerQueueClearedView,
    WorkerRecoveredView,
)
from application.services import (
    SnapshotService,
)
from application.snapshot_views import (
    AnalysisCoverageSnapshot,
    AnalysisOverviewSnapshot,
    MissingSnapshotPayload,
)
from application.web_events import AdminWebEvents
from domain.analysis import CoverageReport, CoverageRequest
from fastapi import APIRouter, HTTPException, Request
from infrastructure.reverse import ReverseAdminClient
from infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    SnapshotRefresher,
    coverage_refresh_seconds,
    coverage_snapshot_key,
    snapshot_meta,
)

from presentation.web_admission import WebAdmission
from presentation.web_models import (
    ProjectCreatePayload,
    WorkerControlPayload,
    WorkerRecoverPayload,
)
from presentation.web_upstream_errors import web_upstream_errors


@dataclass(frozen=True, slots=True)
class WebAnalysisServices:
    snapshots: SnapshotService
    reverse: ReverseAdminClient
    snapshot_refresher: SnapshotRefresher


@dataclass(eq=False, repr=False)
class WebAnalysisController:
    admission: WebAdmission
    services: WebAnalysisServices | None
    events: AdminWebEvents

    def mount(self, router: APIRouter) -> None:
        router.get("/analysis", response_model_exclude_unset=True)(self.analysis_overview)
        router.get("/analysis/projects/{project_id:path}", response_model_exclude_unset=True)(
            self.analysis_project
        )
        router.post("/analysis/projects", response_model_exclude_unset=True)(self.analysis_create)
        router.post("/analysis/projects/{project_id:path}/open", response_model_exclude_unset=True)(
            self.analysis_open
        )
        router.post(
            "/analysis/projects/{project_id:path}/release", response_model_exclude_unset=True
        )(self.analysis_release)
        router.delete("/analysis/projects/{project_id:path}", response_model_exclude_unset=True)(
            self.analysis_delete
        )
        router.put("/analysis/workers/{worker_index}", response_model_exclude_unset=True)(
            self.analysis_worker
        )
        router.get("/analysis/workers", response_model_exclude_unset=True)(self.analysis_workers)
        router.get("/analysis/workers/{worker_index}", response_model_exclude_unset=True)(
            self.analysis_worker_state
        )
        router.post(
            "/analysis/workers/{worker_index}/clear-queue", response_model_exclude_unset=True
        )(self.analysis_worker_clear_queue)
        router.post("/analysis/workers/{worker_index}/recover", response_model_exclude_unset=True)(
            self.analysis_worker_recover
        )
        router.get(
            "/analysis/projects/{project_id:path}/coverage", response_model_exclude_unset=True
        )(self.analysis_coverage)

    async def analysis_overview(self, request: Request) -> AnalysisOverviewSnapshot:
        self.admission.require_user(request)
        snapshot = await self.admission.available(self.services).snapshots.get(REVERSE_OVERVIEW_KEY)
        return AnalysisOverviewSnapshot(
            overview=snapshot.content
            if snapshot is not None and isinstance(snapshot.content, AnalysisOverview)
            else MissingSnapshotPayload(),
            meta=snapshot_meta(snapshot),
        )

    async def analysis_project(
        self, project_id: str, request: Request, folder: str = "/"
    ) -> AnalysisProjectView:
        self.admission.require_user(request)
        api = self.admission.available(self.services)
        with web_upstream_errors():
            session = await api.reverse.session_info(project_id)
            files: AnalysisProjectFiles | InactiveAnalysisFiles = InactiveAnalysisFiles()
            programs: list[AnalysisOpenProgram] = []
            if session.session == "active":
                files = await api.reverse.project_files(project_id, folder)
                programs = await api.reverse.open_programs(project_id)
            return AnalysisProjectView(
                session=session, files=files, programs=programs, folder=folder
            )

    async def analysis_create(
        self, payload: ProjectCreatePayload, request: Request
    ) -> AnalysisProjectOpened:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.reverse.create_project(payload.name, payload.parent_dir)
            await self.events.publish("analysis.project.created", result)
            return result

    async def analysis_open(self, project_id: str, request: Request) -> AnalysisProjectOpened:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.reverse.open_session(project_id)
            await self.events.publish("analysis.project.opened", result)
            return result

    async def analysis_release(self, project_id: str, request: Request) -> AnalysisProjectReleased:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.reverse.release_session(project_id)
            await self.events.publish("analysis.project.released", result)
            return result

    async def analysis_delete(self, project_id: str, request: Request) -> AnalysisProjectDeleted:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.reverse.delete_project(project_id)
            await self.events.publish("analysis.project.deleted", result)
            return result

    async def analysis_worker(
        self, worker_index: int, payload: WorkerControlPayload, request: Request
    ) -> AnalysisWorkerChanged:
        api = self.admission.mutation(request, self.services)
        with web_upstream_errors():
            result = await api.reverse.set_worker_enabled(worker_index, payload.enabled)
            await self.events.publish("analysis.worker.routing_changed", result)
            return result

    async def worker_state(self, api: WebAnalysisServices, worker_index: int) -> AnalysisWorker:
        overview = await api.reverse.overview()
        for worker in overview.workers:
            if worker.worker_index == worker_index:
                return worker
        raise HTTPException(status_code=404, detail="worker not found")

    async def analysis_workers(self, request: Request) -> AnalysisWorkers:
        self.admission.require_user(request)
        with web_upstream_errors():
            overview = await self.admission.available(self.services).reverse.overview()
        return AnalysisWorkers(workers=overview.workers, count=len(overview.workers))

    async def analysis_worker_state(self, worker_index: int, request: Request) -> AnalysisWorker:
        self.admission.require_user(request)
        try:
            return await self.worker_state(self.admission.available(self.services), worker_index)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_clear_queue(
        self, worker_index: int, request: Request
    ) -> WorkerQueueClearedView:
        api = self.admission.mutation(request, self.services)
        try:
            result = await api.reverse.clear_worker_queue(worker_index)
            state = await self.worker_state(api, worker_index)
            response = WorkerQueueClearedView(operation="clear_queue", result=result, worker=state)
            await self.events.publish("analysis.worker.clear_queue", response)
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_recover(
        self, worker_index: int, payload: WorkerRecoverPayload, request: Request
    ) -> WorkerRecoveredView:
        api = self.admission.mutation(request, self.services)
        try:
            result = await api.reverse.recover_worker(
                worker_index, timeout_seconds=payload.timeout_seconds
            )
            state = await self.worker_state(api, worker_index)
            response = WorkerRecoveredView(operation="recover", result=result, worker=state)
            await self.events.publish("analysis.worker.recover", response)
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_coverage(
        self, project_id: str, request: Request, program: str, full: bool = False
    ) -> AnalysisCoverageSnapshot:
        self.admission.require_user(request)
        api = self.admission.available(self.services)
        key = coverage_snapshot_key(project_id, program, full=full)
        snapshot = await api.snapshots.ensure(
            key,
            category="reverse_coverage",
            coverage=CoverageRequest(project_id=project_id, program=program, full=full),
            refresh_after_seconds=coverage_refresh_seconds(full=full),
        )
        api.snapshot_refresher.notify_coverage_requested()
        return AnalysisCoverageSnapshot(
            coverage=AnalysisCoverage(snapshot.content)
            if isinstance(snapshot.content, CoverageReport)
            else MissingSnapshotPayload(),
            meta=snapshot_meta(snapshot),
        )
