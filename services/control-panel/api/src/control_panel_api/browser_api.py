from __future__ import annotations

from briareus_service_discovery import ServiceDiscovery
from briareus_websocket_transport.websocket_proxy import relay_websocket
from fastapi import APIRouter
from starlette.websockets import WebSocket

from control_panel_api.application.identity import PanelTokenIdentity
from control_panel_api.presentation.identity import websocket_principal
from control_panel_api.presentation.identity_websocket import (
    WebSocketRelay,
    relay_authenticated_socket,
)
from control_panel_api.settings import ControlPanelSettings


def build_browser_operator_api_router(
    settings: ControlPanelSettings,
    *,
    identity: PanelTokenIdentity,
    public_origin: str,
    relay: WebSocketRelay = relay_websocket,
    discovery: ServiceDiscovery | None = None,
) -> APIRouter:
    router = APIRouter()

    async def forward(websocket: WebSocket, path: str) -> None:
        principal = await websocket_principal(websocket, identity, public_origin)
        if principal is None:
            return
        if discovery is not None and not await discovery.connected("playwright"):
            await websocket.close(code=4404, reason="service_unavailable")
            return
        await relay_authenticated_socket(
            websocket,
            "ws://playwright:8000" + path,
            headers={"Authorization": f"Bearer {settings.service_token}"},
            principal=principal,
            relay=relay,
        )

    @router.websocket("/admin/api/browser/cdp/page/{target_id}")
    async def browser_remote_debug_socket(websocket: WebSocket, target_id: str) -> None:
        await forward(websocket, f"/cdp/page/{target_id}")

    @router.websocket("/admin/api/browser/operator/ws")
    async def browser_operator_api_socket(websocket: WebSocket) -> None:
        await forward(websocket, "/operator/ws")

    return router
