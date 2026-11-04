from __future__ import annotations

import asyncio

from briareus_json_values import JsonObject, JsonValue, json_object
from fastapi import APIRouter, HTTPException, Request

from control_panel_api.infrastructure.snapshot_worker import (
    REVERSE_OVERVIEW_KEY,
    coverage_refresh_seconds,
    coverage_snapshot_key,
    snapshot_meta,
)

from .context import WebApiContext
from .contracts import (
    ProjectCreatePayload,
    WebApiServices,
    WorkerControlPayload,
    WorkerHeapPayload,
    WorkerRecoverPayload,
)


class AnalysisRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/analysis", self.analysis_overview, methods=["GET"])
        router.add_api_route(
            "/analysis/projects/{project_id:path}", self.analysis_project, methods=["GET"]
        )
        router.add_api_route("/analysis/projects", self.analysis_create, methods=["POST"])
        router.add_api_route(
            "/analysis/projects/{project_id:path}/open", self.analysis_open, methods=["POST"]
        )
        router.add_api_route(
            "/analysis/projects/{project_id:path}/release", self.analysis_release, methods=["POST"]
        )
        router.add_api_route(
            "/analysis/projects/{project_id:path}", self.analysis_delete, methods=["DELETE"]
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}", self.analysis_worker, methods=["PUT"]
        )
        router.add_api_route("/analysis/workers", self.analysis_workers, methods=["GET"])
        router.add_api_route(
            "/analysis/workers/{worker_index}", self.analysis_worker_state, methods=["GET"]
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}/heap", self.analysis_worker_heap, methods=["GET"]
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}/heap", self.analysis_worker_set_heap, methods=["PUT"]
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}/hard-stop",
            self.analysis_worker_hard_stop,
            methods=["POST"],
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}/start", self.analysis_worker_start, methods=["POST"]
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}/clear-queue",
            self.analysis_worker_clear_queue,
            methods=["POST"],
        )
        router.add_api_route(
            "/analysis/workers/{worker_index}/recover",
            self.analysis_worker_recover,
            methods=["POST"],
        )
        router.add_api_route(
            "/analysis/projects/{project_id:path}/coverage", self.analysis_coverage, methods=["GET"]
        )

    async def analysis_overview(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        snapshot = await asyncio.to_thread(
            self.context.available().snapshots.get, REVERSE_OVERVIEW_KEY
        )
        return {
            "overview": snapshot.payload if snapshot is not None else {},
            "meta": snapshot_meta(snapshot),
        }

    async def analysis_project(
        self, project_id: str, request: Request, folder: str = "/"
    ) -> JsonObject:
        self.context.require_user(request)
        api = self.context.available()
        try:
            session = await api.reverse.session_info(project_id)
            files: JsonObject = {}
            programs: list[JsonValue] = []
            if session.get("session") == "active":
                files = await api.reverse.project_files(project_id, folder)
                programs = await api.reverse.open_programs(project_id)
            return {"session": session, "files": files, "programs": programs, "folder": folder}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_create(self, payload: ProjectCreatePayload, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.create_project(payload.name, payload.parent_dir)
            await self.context.publish_management_event(api, "analysis.project.created", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_open(self, project_id: str, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.open_session(project_id)
            await self.context.publish_management_event(api, "analysis.project.opened", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_release(self, project_id: str, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.release_session(project_id)
            await self.context.publish_management_event(api, "analysis.project.released", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_delete(self, project_id: str, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.delete_project(project_id)
            await self.context.publish_management_event(api, "analysis.project.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker(
        self, worker_index: int, payload: WorkerControlPayload, request: Request
    ) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.set_worker_enabled(worker_index, payload.enabled)
            await self.context.publish_management_event(
                api, "analysis.worker.routing_changed", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def worker_state(self, api: WebApiServices, worker_index: int) -> JsonObject:
        overview = await api.reverse.overview()
        workers = overview.get("workers")
        if not isinstance(workers, list):
            workers = []
        for item in workers:
            if isinstance(item, dict) and item.get("worker_index") == worker_index:
                return json_object(item, context="analysis worker state")
        raise HTTPException(status_code=404, detail="worker not found")

    async def analysis_workers(self, request: Request) -> JsonObject:
        self.context.require_user(request)
        try:
            overview = await self.context.available().reverse.overview()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        workers = overview.get("workers")
        items = workers if isinstance(workers, list) else []
        return {"workers": items, "count": len(items)}

    async def analysis_worker_state(self, worker_index: int, request: Request) -> JsonObject:
        self.context.require_user(request)
        try:
            return await self.worker_state(self.context.available(), worker_index)
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_heap(self, worker_index: int, request: Request) -> JsonObject:
        self.context.require_user(request)
        try:
            return await self.context.available().reverse.worker_heap_settings(worker_index)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_set_heap(
        self, worker_index: int, payload: WorkerHeapPayload, request: Request
    ) -> JsonObject:
        service = self.context.mutation(request)
        try:
            result = await service.reverse.set_worker_heap(worker_index, payload.max_heap_mb)
            await self.context.publish_management_event(
                service, "analysis.worker.heap_updated", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_hard_stop(self, worker_index: int, request: Request) -> JsonObject:
        service = self.context.mutation(request)
        try:
            result = await service.reverse.hard_stop_worker(worker_index)
            await self.context.publish_management_event(
                service, "analysis.worker.hard_stopped", result
            )
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_start(self, worker_index: int, request: Request) -> JsonObject:
        service = self.context.mutation(request)
        try:
            result = await service.reverse.start_worker(worker_index)
            await self.context.publish_management_event(service, "analysis.worker.started", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_clear_queue(self, worker_index: int, request: Request) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.clear_worker_queue(worker_index)
            state = await self.worker_state(api, worker_index)
            response: JsonObject = {"operation": "clear_queue", "result": result, "worker": state}
            await self.context.publish_management_event(
                api, "analysis.worker.clear_queue", response
            )
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_worker_recover(
        self, worker_index: int, payload: WorkerRecoverPayload, request: Request
    ) -> JsonObject:
        api = self.context.mutation(request)
        try:
            result = await api.reverse.recover_worker(
                worker_index, timeout_seconds=payload.timeout_seconds
            )
            state = await self.worker_state(api, worker_index)
            response: JsonObject = {"operation": "recover", "result": result, "worker": state}
            await self.context.publish_management_event(api, "analysis.worker.recover", response)
            return response
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    async def analysis_coverage(
        self, project_id: str, request: Request, program: str, full: bool = False
    ) -> JsonObject:
        self.context.require_user(request)
        api = self.context.available()
        key = coverage_snapshot_key(project_id, program, full=full)
        snapshot = await asyncio.to_thread(
            api.snapshots.ensure,
            key,
            category="reverse_coverage",
            parameters={"project_id": project_id, "program": program, "full": full},
            refresh_after_seconds=coverage_refresh_seconds(full=full),
        )
        api.snapshot_refresher.notify_coverage_requested()
        return {"coverage": snapshot.payload, "meta": snapshot_meta(snapshot)}
