"""Authenticated event endpoint composition; application owns the live session."""

from __future__ import annotations

import asyncio
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from fastapi import APIRouter, WebSocket

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._oidc_origin_policy import BROWSER_ORIGIN
from control_panel_api._platform_unix_peer import UnixPlatformPeer
from control_panel_api.application.panel_channel import ContextUnavailable, PanelEmitter, PanelEvent
from control_panel_api.application.panel_event_session import PanelEventSession
from control_panel_api.application.panel_requests import PanelRequests
from control_panel_api.infrastructure.module_replies import NativeToolReply
from control_panel_api.infrastructure.panel_authority import CurrentPanelUser, PanelAuthorityAdapter
from control_panel_api.infrastructure.panel_facades import PanelFacadeAdapter
from control_panel_api.infrastructure.panel_journal import PanelBroker, PanelJournalAdapter
from runtime_peer import PeerClient

from .panel_protocol import DecodedPanelProtocol
from .panel_socket import PanelSocket

if TYPE_CHECKING:
    from control_panel_api._runtime_access_client import RuntimeAccessClient


class SubscribablePanelBroker(PanelBroker, Protocol):
    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[PanelEvent]]: ...


def requested_project(socket: WebSocket) -> UUID | None:
    if (
        socket.headers.getlist("origin") != [BROWSER_ORIGIN]
        or "authorization" in socket.headers
        or set(socket.query_params) - {"project_uuid"}
    ):
        raise ValueError("Panel browser origin required")
    if not socket.query_params:
        return None
    values = socket.query_params.getlist("project_uuid")
    if len(values) != 1:
        raise ValueError("Single Panel project required")
    project = UUID(values[0])
    if project.version != 4 or str(project) != values[0]:
        raise ValueError("Canonical Panel project required")
    return project


@dataclass(frozen=True, slots=True)
class PanelEventController:
    current_context: CurrentPlatformContext
    current_user: CurrentPanelUser
    broker: SubscribablePanelBroker
    access: RuntimeAccessClient | None
    platform: UnixPlatformPeer | None
    resources: PeerClient | None

    async def events(self, socket: WebSocket) -> None:
        try:
            project = requested_project(socket)
        except (ValueError, IndexError):
            await socket.close(code=4403)
            return
        authority = PanelAuthorityAdapter(socket, self.current_context, self.current_user)
        initial = await authority.current(project)
        if isinstance(initial, ContextUnavailable):
            await socket.close(code=4401 if initial.status == 401 else 4403)
            return
        await socket.accept()
        async with self.broker.subscribe() as queue:
            from control_panel_api._owner_events import OwnerSignals

            channel = PanelSocket(socket)
            emitter = PanelEmitter[NativeToolReply](channel)
            journal = PanelJournalAdapter(
                self.broker, queue, OwnerSignals(self.access, self.platform, self.resources)
            )
            facade = PanelFacadeAdapter(socket, self.current_context, self.platform, self.resources)
            requests = PanelRequests[NativeToolReply](
                authority, channel, emitter, journal, DecodedPanelProtocol(), facade, project
            )
            await PanelEventSession[NativeToolReply](
                authority, channel, emitter, journal, requests, project
            ).run(initial)


def panel_events_router(
    *,
    current_context: CurrentPlatformContext,
    current_user: CurrentPanelUser,
    broker: SubscribablePanelBroker,
    access: RuntimeAccessClient | None,
    platform: UnixPlatformPeer | None,
    resources: PeerClient | None,
) -> APIRouter:
    controller = PanelEventController(
        current_context, current_user, broker, access, platform, resources
    )
    router = APIRouter()
    router.websocket("/api/v1/events")(controller.events)
    return router
