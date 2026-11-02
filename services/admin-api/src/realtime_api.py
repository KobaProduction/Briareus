from __future__ import annotations

import asyncio

from application.realtime import RealtimeSession
from application.services import (
    AccountService,
    InvocationAuditService,
    OAuthSessionService,
    SnapshotService,
)
from fastapi import APIRouter
from infrastructure.realtime_snapshots import LegacyRealtimeSnapshots
from infrastructure.web import WebAdminClient
from origin import origin_allowed
from presentation.realtime import JsonRealtimeConnection
from realtime import RealtimeBus
from starlette.websockets import WebSocket, WebSocketDisconnect

from common.settings import AdminApiSettings

_SESSION_KEY = "admin_api_session"


class AdminRealtimeEndpoint:
    def __init__(
        self, settings: AdminApiSettings, bus: RealtimeBus, snapshots: LegacyRealtimeSnapshots
    ) -> None:
        self._settings = settings
        self._bus = bus
        self._snapshots = snapshots

    def _admission_error(self, websocket: WebSocket) -> int | None:
        origin = websocket.headers.get("origin", "")
        public_host = websocket.headers.get("x-forwarded-host") or websocket.headers.get("host", "")
        if not origin_allowed(origin, public_host, self._settings.admin_ui_origin):
            return 4403
        session = websocket.scope.get("session")
        username = session.get(_SESSION_KEY) if isinstance(session, dict) else None
        if not isinstance(username, str) or not username:
            return 4401
        return None

    async def connect(self, websocket: WebSocket) -> None:
        code = self._admission_error(websocket)
        if code is not None:
            await websocket.close(code=code)
            return
        await websocket.accept()
        subscriber = self._bus.register()
        connection = JsonRealtimeConnection(websocket, subscriber, self._snapshots)
        try:
            await RealtimeSession(connection, subscriber.topics).run()
        except (WebSocketDisconnect, asyncio.CancelledError):
            pass
        finally:
            self._bus.unregister(subscriber)


def build_realtime_router(
    settings: AdminApiSettings,
    bus: RealtimeBus,
    accounts: AccountService,
    audit: InvocationAuditService,
    oauth_sessions: OAuthSessionService,
    snapshots: SnapshotService,
    web: WebAdminClient,
) -> APIRouter:
    router = APIRouter()
    reader = LegacyRealtimeSnapshots(bus, accounts, audit, oauth_sessions, snapshots, web)
    endpoint = AdminRealtimeEndpoint(settings, bus, reader)
    router.websocket("/v1/realtime")(endpoint.connect)
    return router
