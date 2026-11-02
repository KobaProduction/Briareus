"""The Resources HTTP consumer preserves the event stream's public JSON contract."""

import json
import unittest
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from cryptography.fernet import Fernet
from fastapi import FastAPI, Request, Response
from httpx import ASGITransport, AsyncClient
from projects.connection_runtime import ConnectionCommand, create_app
from projects.infrastructure.audit_records import PlacementAudit
from starlette.middleware.base import RequestResponseEndpoint

from projects._catalog_ledger import OwnerAuditRow
from runtime_peer import PeerClient, VerifiedOwnerReply
from runtime_peer.event_window_wire import EventWindowRequest


class EventPlatform(PeerClient):
    def __init__(self, command: ConnectionCommand) -> None:
        self.command = command
        self.calls = 0

    async def call[ReplyT](
        self, path: str, payload: dict[str, object], *, decode: Callable[[int, object], ReplyT]
    ) -> VerifiedOwnerReply[ReplyT]:
        if path != "/internal/v1/platform/oidc/actor-context" or payload["project_uuid"] != str(
            self.command.project_uuid
        ):
            raise AssertionError("Exact Platform membership lookup required")
        self.calls += 1
        return VerifiedOwnerReply(
            200,
            decode(
                200,
                {
                    "issuer": self.command.issuer,
                    "subject": self.command.subject,
                    "actor_uuid": str(self.command.actor_uuid),
                    "project_uuid": str(self.command.project_uuid),
                    "role": "operator",
                    "permissions": ["use_resources"],
                    "expires_at": self.command.identity_expires_at.isoformat(),
                },
            ),
        )

    async def close(self) -> None:
        pass


@dataclass
class EventSession:
    rows: tuple[OwnerAuditRow, ...]

    async def scalars(self, _statement: object) -> tuple[OwnerAuditRow, ...]:
        return self.rows


@dataclass
class EventDatabase:
    rows: tuple[OwnerAuditRow, ...]

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[EventSession]:
        yield EventSession(self.rows)

    async def close(self) -> None:
        pass


class ConnectionEventHttpTests(unittest.IsolatedAsyncioTestCase):
    async def test_route_preserves_nulls_order_cursor_and_hides_private_audit_details(self) -> None:
        now = datetime.now(UTC)
        project, actor = uuid4(), uuid4()
        rows = tuple(
            OwnerAuditRow(
                id=uuid4(),
                created_at=now - timedelta(seconds=1) + timedelta(microseconds=index),
                action="node.module.update",
                actor_user_id=None,
                project_id=project,
                object_id=str(uuid4()),
                operation_uuid=uuid4(),
                owner_revision="1",
                details=PlacementAudit(node_uuid=uuid4(), phase="not-public"),
            )
            for index in range(129)
        )
        database = EventDatabase(rows)
        command = ConnectionCommand(
            issuer="https://identity.example",
            subject="operator",
            project_uuid=project,
            actor_uuid=actor,
            action="events.read",
            identity_expires_at=now + timedelta(seconds=20),
            event_window=EventWindowRequest(
                since=(now - timedelta(hours=1)).isoformat(), until=now.isoformat()
            ),
        )
        platform = EventPlatform(command)
        base = FastAPI()

        @base.middleware("http")
        async def ingress(request: Request, call_next: RequestResponseEndpoint) -> Response:
            if request.headers.get("x-fixture-peer") == "control-panel-api":
                request.scope["briareus.service_peer"] = "briareus:control-panel-api"
            return await call_next(request)

        with (
            patch("projects.connection_runtime.create_owner_app", return_value=base),
            patch("projects.connection_runtime.PlatformDatabase", return_value=database),
            patch("projects.connection_runtime.OwnerDatabaseSettings"),
        ):
            app = create_app(platform, Fernet(Fernet.generate_key()))
            async with (
                app.router.lifespan_context(app),
                AsyncClient(
                    transport=ASGITransport(app), base_url="http://fixture.invalid"
                ) as client,
            ):
                response = await client.post(
                    "/internal/v1/resources/connections",
                    json=command.model_dump(mode="json", exclude_unset=True),
                    headers={"x-fixture-peer": "control-panel-api"},
                )
                denied = await client.post(
                    "/internal/v1/resources/connections",
                    json=command.model_dump(mode="json", exclude_unset=True),
                )
        self.assertEqual(response.status_code, 200, response.text)
        payload = json.loads(response.content)
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
        self.assertEqual(payload["items"][0]["project_id"], str(project))
        self.assertEqual(payload["items"][0]["type"], "node.module.update")
        self.assertNotIn(b"not-public", response.content)
        self.assertEqual(denied.status_code, 403)
        self.assertEqual(platform.calls, 1)
