from __future__ import annotations

from fastapi import APIRouter
from starlette.websockets import WebSocket

from common.browser_remote_debug import (
    BROWSER_REMOTE_DEBUG_TTL_SECONDS,
    BrowserRemoteDebugAuthError,
    verify_browser_remote_debug_token,
)
from common.settings import ControlPanelSettings
from common.websocket_proxy import relay_websocket
from control_panel_api.application.identity import PanelIdentityService
from control_panel_api.presentation.identity import websocket_session
from control_panel_api.presentation.identity_websocket import WebSocketRelay, relay_identity_socket


def build_browser_operator_api_router(
    settings: ControlPanelSettings,
    *,
    identity: PanelIdentityService,
    public_origin: str,
    relay: WebSocketRelay = relay_websocket,
) -> APIRouter:
    router = APIRouter()

    @router.websocket("/admin/api/browser/cdp/{token}/page/{target_id}")
    async def browser_remote_debug_socket(websocket: WebSocket, token: str, target_id: str) -> None:
        try:
            session_id = verify_browser_remote_debug_token(
                token,
                settings.service_token,
                None,
                target_id,
                max_age_seconds=BROWSER_REMOTE_DEBUG_TTL_SECONDS,
            )
            session = identity.current(session_id)
            if session is None:
                raise BrowserRemoteDebugAuthError("browser debug session is no longer active")
        except BrowserRemoteDebugAuthError:
            await websocket.close(code=4401)
            return
        await relay_identity_socket(
            websocket,
            f"ws://web:8000/cdp/page/{target_id}",
            headers={"Authorization": f"Bearer {settings.service_token}"},
            identity=identity,
            session=session,
            relay=relay,
        )

    @router.websocket("/admin/api/browser/operator/ws")
    async def browser_operator_api_socket(websocket: WebSocket) -> None:
        session = await websocket_session(websocket, identity, public_origin)
        if session is None:
            return
        await relay_identity_socket(
            websocket,
            "ws://web:8000/operator/ws",
            headers={"Authorization": f"Bearer {settings.service_token}"},
            identity=identity,
            session=session,
            relay=relay,
        )

    return router
