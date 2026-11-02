"""Composition of browser connection management and the Resources owner."""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._panel_events import panel_events
from control_panel_api.application.connections import ConnectionInput as ConnectionInput
from control_panel_api.application.connections import ManageConnections
from control_panel_api.infrastructure.connections import (
    ConnectionCommittedEvents,
    HttpConnectionAuthority,
    ResourcesConnections,
)
from control_panel_api.presentation.connections import ConnectionsController
from runtime_peer import PeerClient


def connection_router(
    *, current_context: CurrentPlatformContext, peer: PeerClient | None
) -> APIRouter:
    router = APIRouter()
    owner = ResourcesConnections(peer) if peer is not None else None

    @router.post("/api/v1/connections")
    async def command(request: Request) -> JSONResponse:
        authority = HttpConnectionAuthority(request, current_context)
        service = ManageConnections(authority, owner, ConnectionCommittedEvents(panel_events))
        return await ConnectionsController(service, authority).command(request)

    return router
