"""Authenticated transport stays responsive while typed owner work is pending."""

import asyncio
import threading
import time
import unittest
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import UUID, uuid4

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._oidc_origin_policy import BROWSER_ORIGIN
from control_panel_api._owner_events import OwnerSignals
from control_panel_api._panel_events import panel_events_router
from control_panel_api.application.module_contracts import ModuleRequest, ModuleScope
from control_panel_api.application.owner_event_relay import (
    OwnerEventPage,
    RelayNotice,
    source_notice,
)
from control_panel_api.application.platform_rpc import PlatformRpc
from control_panel_api.domain.owner_events import (
    EventFeed,
    EventSource,
    EventWindow,
    McpCall,
    McpOwnerEvent,
    OwnerEvent,
)
from control_panel_api.domain.panel_protocol import PanelContext
from control_panel_api.domain.platform_authority import (
    PanelOidcSession,
    PlatformProjectContext,
    PlatformTeamContext,
    ResolvedPlatformUser,
)
from control_panel_api.domain.platform_management import (
    InventoryTeam,
    ManagementCommand,
    ManagementInventory,
    ManagementReceipt,
    RpcFailure,
)
from control_panel_api.domain.realtime_events import EventScope
from control_panel_api.domain.realtime_payloads import OwnerChange, RealtimeData
from control_panel_api.presentation.platform_commands import management_rpc_intent
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient
from starlette.requests import HTTPConnection
from starlette.testclient import WebSocketTestSession
from starlette.types import ASGIApp, Receive, Scope, Send

from runtime_peer import PeerClient


def owner_proof(project: UUID, actor: UUID) -> ResolvedPlatformUser:
    return ResolvedPlatformUser(
        "https://identity.example",
        "fixture",
        actor,
        True,
        "operator",
        datetime.now(UTC) + timedelta(seconds=25),
        (),
        (
            PlatformProjectContext(
                project, "user", actor, ("use_resources", "approve_agent_session")
            ),
        ),
    )


@dataclass
class IdentityFixture:
    actor: UUID = field(default_factory=uuid4)

    async def current(
        self, request: HTTPConnection, project_uuid: UUID | None = None
    ) -> tuple[PanelOidcSession, ResolvedPlatformUser]:
        del request
        expiry = datetime.now(UTC) + timedelta(seconds=25)
        proof = ResolvedPlatformUser(
            "https://identity.example", "fixture", self.actor, True, "operator", expiry, (), ()
        )
        session = PanelOidcSession(
            proof.issuer, proof.subject, "panel", datetime.now(UTC) + timedelta(minutes=10)
        )
        assert project_uuid is None
        return session, proof

    async def user(self, request: HTTPConnection, project_uuid: UUID | None = None) -> JSONResponse:
        del request, project_uuid
        raise AssertionError("This transport test never requests the user projection")


class CompletionMiddleware:
    def __init__(self, app: ASGIApp, completed: threading.Event) -> None:
        self.app, self.completed = app, completed

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await self.app(scope, receive, send)
        finally:
            if scope["type"] == "websocket":
                self.completed.set()


def transport_app(identity: IdentityFixture, completed: threading.Event) -> FastAPI:
    app = FastAPI()
    app.add_middleware(CompletionMiddleware, completed=completed)
    app.include_router(
        panel_events_router(current_context=identity.current, current_user=identity.user)
    )
    return app


def finish(socket: WebSocketTestSession, completed: threading.Event) -> None:
    socket.close()
    if not completed.wait(2):
        raise AssertionError("Disconnected endpoint did not finish its background cleanup")


class PanelEventLoopTests(unittest.TestCase):
    def test_slow_owner_does_not_delay_rpc_and_delivery_has_sequence(self) -> None:
        entered, completed = threading.Event(), threading.Event()

        async def slow(
            source: OwnerSignals, proof: ResolvedPlatformUser
        ) -> AsyncIterator[RelayNotice]:
            del source
            assert proof.expires_at.tzinfo is not None
            entered.set()
            await asyncio.Event().wait()
            yield source_notice(EventFeed("platform"), "source.connected")

        app = transport_app(IdentityFixture(), completed)
        with (
            patch("control_panel_api._owner_events.OwnerSignals.read", slow),
            TestClient(app) as client,
            client.websocket_connect(
                "/api/v1/events", headers={"origin": BROWSER_ORIGIN}
            ) as socket,
        ):
            frame = socket.receive_json()["params"]
            self.assertEqual(frame["sequence"], 1)
            self.assertEqual(len(frame["stream_id"]), 36)
            self.assertTrue(entered.wait(2), "Owner relay was not entered")
            began = time.monotonic()
            socket.send_json(
                {"jsonrpc": "2.0", "id": "heartbeat", "method": "system.ping", "params": {}}
            )
            self.assertEqual(socket.receive_json()["id"], "heartbeat")
            self.assertLess(time.monotonic() - began, 0.7)
            finish(socket, completed)

    def test_module_preparation_does_not_block_heartbeat(self) -> None:
        entered, completed, project = threading.Event(), threading.Event(), uuid4()

        async def slow(
            *,
            socket: WebSocket,
            request: ModuleRequest,
            current_context: CurrentPlatformContext,
            resources: PeerClient | None,
        ) -> ModuleScope:
            del socket, current_context, resources
            assert request.project_uuid == project and request.command is None
            entered.set()
            await asyncio.Event().wait()
            return ModuleScope(items=())

        app = transport_app(IdentityFixture(), completed)
        with (
            patch("control_panel_api._node_files.files_call", slow),
            TestClient(app) as client,
            client.websocket_connect(
                "/api/v1/events", headers={"origin": BROWSER_ORIGIN}
            ) as socket,
        ):
            socket.receive_json()
            socket.send_json(
                {
                    "jsonrpc": "2.0",
                    "id": "files",
                    "method": "files.resources",
                    "params": {"project_uuid": str(project)},
                }
            )
            self.assertTrue(entered.wait(2), "The valid module request never reached its owner")
            began = time.monotonic()
            socket.send_json(
                {"jsonrpc": "2.0", "id": "ping", "method": "system.ping", "params": {}}
            )
            while True:
                reply = socket.receive_json()
                if reply.get("id") == "ping":
                    break
            self.assertLess(time.monotonic() - began, 0.3)
            finish(socket, completed)


@dataclass
class JournalFixture:
    available: frozenset[EventSource]
    page: OwnerEventPage
    project: UUID

    async def read(self, feed: EventFeed, window: EventWindow) -> OwnerEventPage:
        assert feed.source in self.available and feed.project == self.project
        assert window.until >= window.since
        return self.page


@dataclass(frozen=True)
class Published:
    topic: str
    type: str
    data: RealtimeData
    visibility: EventScope


@dataclass
class PublisherFixture:
    records: list[Published] = field(default_factory=list)

    async def emit(
        self,
        topic: str,
        event_type: str,
        data: RealtimeData,
        *,
        visibility: EventScope,
        event_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        assert event_id and occurred_at is not None and occurred_at.tzinfo is not None
        self.records.append(Published(topic, event_type, data, visibility))


@dataclass
class AuthorityFixture:
    context: PanelContext

    async def current(self) -> PanelContext | None:
        return self.context


@dataclass
class ManagementFixture:
    team: UUID
    actor: UUID
    calls: list[ManagementCommand] = field(default_factory=list)

    async def execute(
        self, context: PanelContext, command: ManagementCommand, expires_at: datetime
    ) -> ManagementReceipt:
        assert context.proof.user_uuid == self.actor and expires_at > datetime.now(UTC)
        self.calls.append(command)
        return ManagementReceipt(
            200,
            ManagementInventory(
                (), (InventoryTeam(self.team, "Team", uuid4(), (self.actor,)),), (), False
            ),
        )


class TeamRpcTests(unittest.IsolatedAsyncioTestCase):
    async def test_actual_call_metadata_uses_scoped_mcp_topic_and_keeps_owner_cursor(self) -> None:
        project, actor = uuid4(), uuid4()
        event = McpOwnerEvent(
            uuid4(),
            "mcp.call.completed",
            datetime.now(UTC).isoformat(),
            actor,
            project,
            uuid4(),
            uuid4(),
            McpCall("terminal", "job_start", "completed", uuid4(), uuid4(), uuid4(), 10),
        )
        journal = JournalFixture(
            frozenset({"access"}), OwnerEventPage((event,), False, None), project
        )
        source, publisher = OwnerSignals(None, None, None), PublisherFixture()
        with (
            patch("control_panel_api._owner_events.PrivateOwnerJournals", return_value=journal),
            patch("control_panel_api._owner_events.panel_events", publisher),
        ):
            notices = [notice async for notice in source.read(owner_proof(project, actor))]
        self.assertEqual(len(publisher.records), 1)
        record = publisher.records[0]
        self.assertEqual((record.topic, record.type), ("mcp.calls", "call.completed"))
        assert isinstance(record.data, OwnerChange)
        assert isinstance(record.data.event, McpOwnerEvent)
        self.assertEqual(record.data.event.call.tool, "job_start")
        self.assertEqual(record.visibility.project, project)
        self.assertIn(("access", str(project)), source.windows)
        self.assertTrue(source.health[("access", str(project))])
        self.assertEqual(notices[0].type, "source.connected")

    async def test_release_publication_does_not_block_later_node_phase_events(self) -> None:
        project, actor = uuid4(), uuid4()
        events = tuple(
            OwnerEvent(
                uuid4(), kind, datetime.now(UTC).isoformat(), actor, project, uuid4(), uuid4()
            )
            for kind in ("node.module.publish", "node.module.succeeded")
        )
        journal = JournalFixture(
            frozenset({"resources"}), OwnerEventPage(events, False, None), project
        )
        source, publisher = OwnerSignals(None, None, None), PublisherFixture()
        with (
            patch("control_panel_api._owner_events.PrivateOwnerJournals", return_value=journal),
            patch("control_panel_api._owner_events.panel_events", publisher),
        ):
            notices = [notice async for notice in source.read(owner_proof(project, actor))]
        self.assertEqual(
            [item.type for item in publisher.records],
            ["node.module.publish", "node.module.succeeded"],
        )
        self.assertTrue(source.health[("resources", str(project))])
        self.assertEqual(notices[0].type, "source.connected")

    async def test_team_read_does_not_allow_global_inventory_or_foreign_team(self) -> None:
        team, actor = uuid4(), uuid4()
        expiry = datetime.now(UTC) + timedelta(seconds=20)
        proof = ResolvedPlatformUser(
            "https://identity.example",
            "fixture",
            actor,
            True,
            "user",
            expiry,
            (PlatformTeamContext(team, False),),
            (),
        )
        session = PanelOidcSession(proof.issuer, proof.subject, "panel", expiry)
        owner = ManagementFixture(team, actor)
        rpc = PlatformRpc(AuthorityFixture(PanelContext(session, proof)), owner)
        result = await rpc.execute(management_rpc_intent("platform.team", {"id": str(team)}))
        assert isinstance(result, ManagementInventory)
        self.assertEqual([item.id for item in result.teams], [team])
        self.assertEqual(owner.calls[0].action, "team.read")
        for method, params in (("platform.inventory", {}), ("platform.team", {"id": str(uuid4())})):
            with self.subTest(method=method), self.assertRaises(RpcFailure):
                await rpc.execute(management_rpc_intent(method, params))
        self.assertEqual(len(owner.calls), 1)
