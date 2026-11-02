"""The real management HTTP route serializes public event pages without audit data."""

import json
import unittest
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from projects._panel_management import ManagementQuery, management_router

from runtime_peer.event_projection import EventPage
from runtime_peer.event_window import EventWindow


@dataclass(frozen=True)
class AuditFixture:
    id: UUID
    created_at: datetime
    action: str
    actor_user_id: UUID | None
    project_id: UUID | None
    object_id: str
    operation_uuid: UUID
    details: dict[str, object] = field(default_factory=dict)


@dataclass
class EventService:
    rows: tuple[AuditFixture, ...]
    calls: int = 0

    async def execute(self, query: ManagementQuery, _deadline: datetime) -> EventPage:
        self.calls += 1
        return EventWindow.parse(query.data).result(self.rows)


class ManagementAuthority:
    async def verify_management(self, _request: Request, _payload: dict[str, object]) -> datetime:
        return datetime.now(UTC) + timedelta(seconds=15)


class ManagementEventHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_preserves_nulls_order_cursor_and_public_keys(self) -> None:
        now = datetime.now(UTC) - timedelta(seconds=1)
        rows = tuple(
            AuditFixture(
                uuid4(),
                now + timedelta(microseconds=index),
                "panel.team.rename",
                None,
                None,
                str(uuid4()),
                uuid4(),
                details={"private": "not-public"},
            )
            for index in range(129)
        )
        service = EventService(rows)
        router = management_router(lambda: service, ManagementAuthority())
        route = next(item for item in router.routes if isinstance(item, APIRoute))
        self.assertEqual(route.path, "/internal/v1/platform/manage")
        endpoint = cast(Callable[[Request], Awaitable[JSONResponse]], route.endpoint)
        command = {
            "issuer": "https://identity.example",
            "subject": "operator",
            "operation_uuid": str(uuid4()),
            "action": "events.read",
            "data": {
                "since": (now - timedelta(hours=1)).isoformat(),
                "until": (now + timedelta(seconds=1)).isoformat(),
            },
        }
        request = Request(
            {
                "type": "http",
                "briareus.unix_peer_uid": 1001,
                "headers": [(b"authorization", b"Bearer fixture")],
            }
        )
        request._body = json.dumps(command).encode()
        response = await endpoint(request)
        denied = await endpoint(
            Request({"type": "http", "briareus.unix_peer_uid": 1001, "headers": []})
        )
        self.assertEqual(response.status_code, 200)
        payload = json.loads(bytes(response.body))
        self.assertEqual(set(payload), {"truncated", "next", "items"})
        self.assertFalse(payload["truncated"])
        self.assertEqual(payload["next"], [rows[127].created_at.isoformat(), str(rows[127].id)])
        self.assertEqual(
            [item["event_id"] for item in payload["items"]], [str(row.id) for row in rows[:128]]
        )
        self.assertEqual(
            set(payload["items"][0]),
            {
                "event_id",
                "occurredAt",
                "type",
                "actor_id",
                "project_id",
                "entity_id",
                "operation_id",
            },
        )
        self.assertIsNone(payload["items"][0]["actor_id"])
        self.assertIsNone(payload["items"][0]["project_id"])
        self.assertEqual(payload["items"][0]["type"], "team.rename")
        self.assertNotIn(b"not-public", bytes(response.body))
        self.assertEqual(response.headers["cache-control"], "no-store")
        self.assertEqual(denied.status_code, 401)
        self.assertEqual(service.calls, 1)
