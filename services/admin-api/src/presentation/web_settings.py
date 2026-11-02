"""Retained settings HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.panel_views import (
    RecordsRemoved,
    SettingsSnapshot,
)
from application.services import (
    InvocationAuditService,
)
from application.settings_command import SettingsPayload
from application.web_events import AdminWebEvents
from application.web_settings import (
    UpdateWebSettings,
    WebSettingsConflict,
    WebSettingsRejected,
    WebSettingsSnapshotReader,
)
from fastapi import APIRouter, HTTPException, Request, status

from presentation.web_admission import WebAdmission


@dataclass(frozen=True, slots=True)
class WebSettingsServices:
    audit: InvocationAuditService
    reader: WebSettingsSnapshotReader
    update: UpdateWebSettings


@dataclass(eq=False, repr=False)
class WebSettingsController:
    admission: WebAdmission
    services: WebSettingsServices | None
    events: AdminWebEvents

    def mount(self, router: APIRouter) -> None:
        router.get("/settings")(self.settings_get)
        router.put("/settings")(self.settings_update)
        router.post("/settings/cleanup-logs")(self.settings_cleanup)

    async def settings_get(self, request: Request) -> SettingsSnapshot:
        self.admission.require_user(request)
        return await self.admission.available(self.services).reader.read()

    async def settings_update(self, payload: SettingsPayload, request: Request) -> SettingsSnapshot:
        api = self.admission.mutation(request, self.services)
        try:
            return await api.update.execute(payload)
        except WebSettingsConflict as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "code": "settings_conflict",
                    "message": "settings changed since they were loaded; reload before saving",
                    "current_revision": exc.current_revision,
                },
            ) from exc
        except WebSettingsRejected as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    async def settings_cleanup(self, request: Request) -> RecordsRemoved:
        api = self.admission.mutation(request, self.services)
        removed = await api.audit.cleanup()
        response: RecordsRemoved = RecordsRemoved(removed=removed)
        await self.events.publish("calls.retention_applied", response)
        return response
