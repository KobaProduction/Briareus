"""Retained telemetry HTTP adapters with focused dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from application.frontend_telemetry import FrontendTelemetryBatch
from application.telemetry_receipt import TelemetryEnqueueReceipt
from fastapi import APIRouter, HTTPException, Request
from telemetry_ingest import FrontendTelemetryProxy

from presentation.web_admission import WebAdmission


@dataclass(frozen=True, slots=True)
class WebTelemetryServices:
    telemetry: FrontendTelemetryProxy | None


@dataclass(eq=False, repr=False)
class WebTelemetryController:
    admission: WebAdmission
    services: WebTelemetryServices | None

    def mount(self, router: APIRouter) -> None:
        router.post("/telemetry")(self.frontend_telemetry)

    async def frontend_telemetry(
        self, payload: FrontendTelemetryBatch, request: Request
    ) -> TelemetryEnqueueReceipt:
        api = self.admission.mutation(request, self.services)
        if api.telemetry is None:
            raise HTTPException(status_code=503, detail="frontend telemetry unavailable")
        return api.telemetry.enqueue(tuple(event.domain() for event in payload.events))
