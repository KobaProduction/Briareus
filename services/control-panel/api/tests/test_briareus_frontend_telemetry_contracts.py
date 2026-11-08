from __future__ import annotations

import unittest
from unittest.mock import Mock

from control_panel_api.domain.frontend_telemetry import FrontendTelemetryEvent
from control_panel_api.presentation.admin_routes.telemetry import TelemetryRoutes
from control_panel_api.telemetry_ingest import FrontendTelemetryProxy, TelemetryUpstream
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient


class FrontendTelemetryContracts(unittest.TestCase):
    @staticmethod
    def event(identifier: str) -> FrontendTelemetryEvent:
        return FrontendTelemetryEvent(
            id=identifier,
            name="api.completed",
            level="info",
            occurredAt="2026-11-08T12:00:00Z",
            route="#dashboard",
            attributes={"status": 200, "token": "fixture-private-value"},
        )

    def test_bounded_queue_redacts_before_storing_typed_events(self) -> None:
        proxy = FrontendTelemetryProxy(TelemetryUpstream(url=""), max_batches=1)
        first = proxy.enqueue([self.event("first")])
        second = proxy.enqueue([self.event("second")])
        self.assertEqual(first.accepted, 1)
        self.assertEqual(second.queued_batches, 1)
        self.assertEqual(second.dropped_batches, 1)
        retained = proxy.queue.get_nowait()
        self.assertEqual(retained[0].id, "second")
        self.assertEqual(retained[0].attributes["status"], 200)
        self.assertNotIn("fixture-private-value", retained[0].model_dump_json())
        self.assertNotIn("durationMs", retained[0].model_dump(exclude_unset=True))
        proxy.queue.task_done()

    def test_http_acceptance_keeps_wire_shape_and_rejects_malformed_events(self) -> None:
        context = Mock()
        proxy = FrontendTelemetryProxy(TelemetryUpstream(url=""))
        context.mutation.return_value.telemetry = proxy
        app = FastAPI()
        router = APIRouter()
        TelemetryRoutes(context).register(router)
        app.include_router(router)
        with TestClient(app) as client:
            response = client.post("/telemetry", json={"events": [self.event("http").to_json()]})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json(), {
                "accepted": 1, "queued_batches": 1, "dropped_batches": 0,
            })
            malformed = client.post("/telemetry", json={"events": [{"name": "bad"}]})
            self.assertEqual(malformed.status_code, 422)
            self.assertEqual(proxy.queue.qsize(), 1)
