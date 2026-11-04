from __future__ import annotations

from briareus_json_values import JsonObject
from fastapi import APIRouter, HTTPException, Request

from .context import WebApiContext
from .contracts import (
    FrontendTelemetryBatch,
)


class TelemetryRoutes:
    def __init__(self, context: WebApiContext) -> None:
        self.context = context

    def register(self, router: APIRouter) -> None:
        router.add_api_route("/telemetry", self.frontend_telemetry, methods=["POST"])

    async def frontend_telemetry(
        self, payload: FrontendTelemetryBatch, request: Request
    ) -> JsonObject:
        api = self.context.mutation(request)
        if api.telemetry is None:
            raise HTTPException(status_code=503, detail="frontend telemetry unavailable")
        return api.telemetry.enqueue(list(payload.events))
