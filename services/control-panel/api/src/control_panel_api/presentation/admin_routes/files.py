from __future__ import annotations

import asyncio
import posixpath
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, Query, Request, UploadFile
from starlette.responses import FileResponse

from control_panel_api.domain.admin_data.files import FileDeletion, FileEntry, FileStats
from control_panel_api.domain.dashboard import EmptyData
from control_panel_api.infrastructure.snapshot_worker import (
    WORKSPACE_STATS_KEY,
    snapshot_meta,
)

from .context import WebApiContext
from .view_contracts import FilesView


class FilesRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route(
            "/files", self.files_list, methods=["GET"], response_model_exclude_unset=True
        )
        router.add_api_route(
            "/files/upload", self.files_upload, methods=["POST"], response_model_exclude_unset=True
        )
        router.add_api_route(
            "/files/mkdir", self.files_mkdir, methods=["POST"], response_model_exclude_unset=True
        )
        router.add_api_route(
            "/files/download",
            self.files_download,
            methods=["GET"],
            response_model_exclude_unset=True,
        )
        router.add_api_route(
            "/files", self.files_delete, methods=["DELETE"], response_model_exclude_unset=True
        )

    async def files_list(
        self,
        request: Request,
        path: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(500, ge=1, le=1000),
    ) -> FilesView:
        self.context.require_user(request)
        api = self.context.available()
        current = path.strip().strip("/")
        listing, cached_stats = await asyncio.gather(
            asyncio.to_thread(api.files.list, current, offset=offset, limit=limit),
            asyncio.to_thread(api.snapshots.get, WORKSPACE_STATS_KEY),
        )
        stats = cached_stats.payload if cached_stats is not None else None
        if stats is not None and not isinstance(stats, FileStats):
            raise TypeError("workspace snapshot has incompatible payload")
        return FilesView(
            listing=listing,
            current_path=current,
            parent_path=posixpath.dirname(current) if current else "",
            stats=stats if stats is not None else EmptyData(),
            stats_meta=snapshot_meta(cached_stats) or EmptyData(),
        )

    async def files_upload(
        self,
        request: Request,
        file: Annotated[UploadFile, File()],
        path: Annotated[str, Form()] = "",
        overwrite: Annotated[bool, Form()] = False,
    ) -> FileEntry:
        api = self.context.mutation(request)
        current = path.strip().strip("/")
        name = Path(file.filename or "upload.bin").name
        destination = posixpath.join(current, name) if current else name
        try:
            result = await asyncio.to_thread(
                api.files.upload, file.file, destination=destination, overwrite=overwrite
            )
            await self.context.publish_management_event(api, "files.uploaded", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def files_mkdir(
        self, request: Request, path: Annotated[str, Form()] = "", name: Annotated[str, Form()] = ""
    ) -> FileEntry:
        api = self.context.mutation(request)
        current = path.strip().strip("/")
        clean = name.strip().strip("/")
        if not clean or "/" in clean or "\\\\" in clean:
            raise HTTPException(status_code=400, detail="a single directory name is required")
        destination = posixpath.join(current, clean) if current else clean
        try:
            result = await asyncio.to_thread(api.files.mkdir, destination)
            await self.context.publish_management_event(api, "files.directory_created", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def files_download(self, request: Request, path: str) -> FileResponse:
        self.context.require_user(request)
        api = self.context.available()
        try:
            info = await asyncio.to_thread(api.files.info, path)
            file_path = await asyncio.to_thread(api.files.path_for, path)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if info.type != "file":
            raise HTTPException(status_code=400, detail="path is not a file")
        return FileResponse(
            file_path,
            filename=info.name or file_path.name,
            media_type=info.mime_type or "application/octet-stream",
        )

    async def files_delete(
        self, request: Request, path: str, recursive: bool = False
    ) -> FileDeletion:
        api = self.context.mutation(request)
        try:
            result = await asyncio.to_thread(api.files.delete, path, recursive=recursive)
            await self.context.publish_management_event(api, "files.deleted", result)
            return result
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
