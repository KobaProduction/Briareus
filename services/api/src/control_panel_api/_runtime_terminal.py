"""Human runtime composition; private owner commands outside the live MCP plane."""

from uuid import UUID

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from control_panel_api._oidc_membership import CurrentPlatformContext
from control_panel_api._panel_events import panel_events
from control_panel_api._runtime_access_client import RuntimeAccessClient
from control_panel_api.application.runtime_effect import HumanRuntimeEffects
from control_panel_api.application.runtime_effect_contracts import RuntimeHand
from control_panel_api.application.runtime_effect_contracts import (
    TerminalCommand as TerminalCommand,
)
from control_panel_api.infrastructure.runtime_effect import (
    CurrentRuntimeGrants,
    HttpRuntimeAuthority,
    PrivateRuntimeHand,
    RuntimeCallObservations,
)
from control_panel_api.infrastructure.runtime_replies import NativeRuntimeReply
from control_panel_api.presentation.runtime_effect import RuntimeController
from runtime_peer import PeerClient


def terminal_runtime_router(
    *,
    current_context: CurrentPlatformContext,
    access: RuntimeAccessClient,
    terminal: PeerClient,
    files: PeerClient | None = None,
    web: PeerClient | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/api/v1/runtime")
    peers = {"terminal": terminal, "files": files, "web": web}

    def controller(request: Request, hand: RuntimeHand) -> RuntimeController:
        authority = HttpRuntimeAuthority(request, current_context)
        peer = peers[hand]
        service = HumanRuntimeEffects[NativeRuntimeReply](
            authority,
            CurrentRuntimeGrants(access),
            PrivateRuntimeHand(peer) if peer is not None else None,
            RuntimeCallObservations(panel_events),
        )
        return RuntimeController(service, authority)

    @router.get("/resources")
    async def resources(
        request: Request, project_uuid: UUID, hand: RuntimeHand = "terminal"
    ) -> JSONResponse:
        return await controller(request, hand).resources(project_uuid, hand)

    @router.post("/terminal/call")
    async def terminal_call(request: Request) -> JSONResponse:
        return await controller(request, "terminal").call(request, "terminal")

    @router.post("/files/call")
    async def files_call(request: Request) -> JSONResponse:
        return await controller(request, "files").call(request, "files")

    @router.post("/web/call")
    async def web_call(request: Request) -> JSONResponse:
        return await controller(request, "web").call(request, "web")

    return router
