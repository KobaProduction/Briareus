"""Retained files HTTP adapters with focused dependencies."""

from __future__ import annotations

import asyncio
import posixpath
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Annotated

from application.services import (
    SnapshotService,
)
from application.snapshot_views import (
    MissingSnapshotPayload,
)
from application.web_events import AdminWebEvents
from application.workspace_views import FileWorkspaceStats
from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from infrastructure.files import FileAdminStore
from infrastructure.snapshot_worker import (
    WORKSPACE_STATS_KEY,
    snapshot_meta,
)
from starlette.responses import FileResponse, JSONResponse

from modules.workspace_compat.domain.receipts import (
    WorkspaceFileEntry,
)
from presentation.web_admission import WebAdmission
from presentation.workspace_views import WorkspaceListing


@dataclass(frozen=True, slots=True)
class WebFileServices:
    snapshots: SnapshotService
    files: FileAdminStore


@dataclass(eq=False, repr=False)
class WebFileController:
    admission: WebAdmission
    services: WebFileServices | None
    events: AdminWebEvents

    def mount(self, router: APIRouter) -> None:
        router.get("/files")(self.files_list)
        router.post("/files/upload")(self.files_upload)
        router.post("/files/mkdir")(self.files_mkdir)
        router.get("/files/download")(self.files_download)
        router.delete("/files")(self.files_delete)

    async def files_list(
        self,
        request: Request,
        path: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(500, ge=1, le=1000),
    ) -> WorkspaceListing:
        self.admission.require_user(request)
        api = self.admission.available(self.services)
        current = path.strip().strip("/")
        listing, cached_stats = await asyncio.gather(
            asyncio.to_thread(api.files.list, current, offset=offset, limit=limit),
            api.snapshots.get(WORKSPACE_STATS_KEY),
        )
        return WorkspaceListing(
            listing=listing,
            current_path=current,
            parent_path=posixpath.dirname(current) if current else "",
            stats=cached_stats.content
            if cached_stats is not None and isinstance(cached_stats.content, FileWorkspaceStats)
            else MissingSnapshotPayload(),
            stats_meta=snapshot_meta(cached_stats),
        )

    async def files_upload(
        self,
        request: Request,
        file: Annotated[UploadFile, File()],
        path: Annotated[str, Form()] = "",
        overwrite: Annotated[bool, Form()] = False,
    ) -> JSONResponse:
        api = self.admission.mutation(request, self.services)
        current = path.strip().strip("/")
        name = Path(file.filename or "upload.bin").name
        destination = posixpath.join(current, name) if current else name
        try:
            result = await asyncio.to_thread(
                api.files.upload, file.file, destination=destination, overwrite=overwrite
            )
            await self.events.publish("files.uploaded", result)
            return JSONResponse(asdict(result))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def files_mkdir(
        self, request: Request, path: Annotated[str, Form()] = "", name: Annotated[str, Form()] = ""
    ) -> JSONResponse:
        api = self.admission.mutation(request, self.services)
        current = path.strip().strip("/")
        clean = name.strip().strip("/")
        if not clean or "/" in clean or "\\\\" in clean:
            raise HTTPException(status_code=400, detail="a single directory name is required")
        destination = posixpath.join(current, clean) if current else clean
        try:
            result = await asyncio.to_thread(api.files.mkdir, destination)
            await self.events.publish("files.directory_created", result)
            return JSONResponse(asdict(result))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def files_download(self, request: Request, path: str) -> FileResponse:
        self.admission.require_user(request)
        api = self.admission.available(self.services)
        try:
            info = await asyncio.to_thread(api.files.info, path)
            file_path = await asyncio.to_thread(api.files.path_for, path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not isinstance(info, WorkspaceFileEntry):
            raise HTTPException(status_code=400, detail="path is not a file")
        return FileResponse(
            file_path,
            filename=info.name or file_path.name,
            media_type=info.mime_type or "application/octet-stream",
        )

    async def files_delete(
        self, request: Request, path: str, recursive: bool = False
    ) -> JSONResponse:
        api = self.admission.mutation(request, self.services)
        try:
            result = await asyncio.to_thread(api.files.delete, path, recursive=recursive)
            await self.events.publish("files.deleted", result)
            return JSONResponse(asdict(result))
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
