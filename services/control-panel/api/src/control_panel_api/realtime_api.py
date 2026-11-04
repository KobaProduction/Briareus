from __future__ import annotations

import asyncio
from dataclasses import dataclass

from briareus_json_values import JsonValue
from briareus_zitadel_tokens import VerifiedPrincipal
from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict, ValidationError
from starlette.websockets import WebSocket, WebSocketDisconnect

from control_panel_api.application.identity import PanelTokenIdentity
from control_panel_api.application.services import (
    AccountService,
    InvocationAuditService,
    SnapshotService,
)
from control_panel_api.dashboard_state import build_dashboard_state
from control_panel_api.infrastructure.web import WebAdminClient
from control_panel_api.presentation.identity import websocket_principal
from control_panel_api.presentation.identity_websocket import (
    token_socket_active,
    watch_token_expiry,
)
from control_panel_api.realtime import REALTIME_TOPICS, RealtimeBus, RealtimeEnvelope


class RealtimeCommand(BaseModel):
    model_config = ConfigDict(extra="ignore")
    type: str = ""
    topics: str | list[JsonValue] | None = None
    topic: str = ""

    @property
    def requested_topics(self) -> list[str]:
        if isinstance(self.topics, str):
            return [self.topics]
        if isinstance(self.topics, list):
            return [str(item) for item in self.topics]
        return [self.topic] if self.topic else []


@dataclass(frozen=True)
class RealtimeServices:
    bus: RealtimeBus
    accounts: AccountService
    audit: InvocationAuditService
    snapshots: SnapshotService
    web: WebAdminClient
    identity: PanelTokenIdentity
    public_origin: str


class RealtimeConnection:
    def __init__(
        self, websocket: WebSocket, principal: VerifiedPrincipal, services: RealtimeServices
    ) -> None:
        self.websocket = websocket
        self.principal = principal
        self.services = services
        self.subscriber = services.bus.register()

    async def admitted(self) -> bool:
        return await token_socket_active(self.websocket, self.principal)

    async def topic_snapshot(self, topic: str) -> RealtimeEnvelope | None:
        services = self.services
        if topic == "mcp.calls":
            events = await asyncio.to_thread(services.audit.recent, limit=100)
            return RealtimeEnvelope(
                topic=topic,
                type="snapshot",
                data={
                    "events": [item.model_dump(mode="json") for item in events],
                    "count": len(events),
                },
            )
        if topic == "browser.runtime":
            try:
                return RealtimeEnvelope(
                    topic=topic, type="snapshot", data=await services.web.status()
                )
            except Exception as error:
                return RealtimeEnvelope(
                    topic=topic, type="snapshot", data={"available": False, "error": str(error)}
                )
        if topic == "system.metrics":
            state = await build_dashboard_state(
                services.accounts, services.audit, services.snapshots
            )
            return RealtimeEnvelope(topic=topic, type="snapshot", data=state)
        cached = services.bus.snapshot(topic)
        if not isinstance(cached, dict) or cached.get("data") is None:
            return None
        return RealtimeEnvelope(topic=topic, type="snapshot", data=cached.get("data"))

    async def subscribe(self, requested: list[str]) -> None:
        try:
            topics = [self.services.bus.validate_topic(item) for item in requested]
        except ValueError as error:
            await self.websocket.send_json(
                {"version": 1, "type": "error", "code": "invalid_topic", "message": str(error)}
            )
            return
        self.subscriber.topics.update(topics)
        await self.websocket.send_json(
            {"version": 1, "type": "subscribed", "topics": sorted(self.subscriber.topics)}
        )
        for topic in topics:
            data = await self.topic_snapshot(topic)
            if not await self.admitted():
                return
            if data is not None:
                await self.websocket.send_json(data.model_dump(mode="json"))

    async def receive_commands(self) -> None:
        while True:
            message = await self.websocket.receive_json()
            if not await self.admitted():
                return
            try:
                command = RealtimeCommand.model_validate(message)
            except ValidationError:
                continue
            if command.type == "subscribe":
                await self.subscribe(command.requested_topics)
            elif command.type == "unsubscribe":
                self.subscriber.topics.difference_update(command.requested_topics)
                await self.websocket.send_json(
                    {"version": 1, "type": "unsubscribed", "topics": sorted(self.subscriber.topics)}
                )
            elif command.type == "ping":
                await self.websocket.send_json({"version": 1, "type": "pong"})

    async def send_events(self) -> None:
        while True:
            event = await self.subscriber.queue.get()
            if not await self.admitted():
                return
            await self.websocket.send_json(event)

    async def run(self) -> None:
        stopped = asyncio.Event()
        tasks = {
            asyncio.create_task(self.receive_commands()),
            asyncio.create_task(self.send_events()),
            asyncio.create_task(watch_token_expiry(self.websocket, self.principal, stopped)),
        }
        try:
            await self.websocket.send_json(
                {"version": 1, "type": "ready", "topics": sorted(REALTIME_TOPICS)}
            )
            done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in pending:
                task.cancel()
            await asyncio.gather(*pending, return_exceptions=True)
            await asyncio.gather(*done, return_exceptions=True)
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            stopped.set()
            self.services.bus.unregister(self.subscriber)
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def build_realtime_router(
    bus: RealtimeBus,
    accounts: AccountService,
    audit: InvocationAuditService,
    snapshots: SnapshotService,
    web: WebAdminClient,
    *,
    identity: PanelTokenIdentity,
    public_origin: str,
) -> APIRouter:
    services = RealtimeServices(bus, accounts, audit, snapshots, web, identity, public_origin)
    router = APIRouter()

    @router.websocket("/admin/api/realtime")
    async def realtime_socket(websocket: WebSocket) -> None:
        session = await websocket_principal(websocket, identity, public_origin)
        if session is None:
            return
        await websocket.accept(
            subprotocol="briareus.v1"
            if "briareus.v1" in websocket.scope.get("subprotocols", [])
            else None
        )
        await RealtimeConnection(websocket, session, services).run()

    return router
