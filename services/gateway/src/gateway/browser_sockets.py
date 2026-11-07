from __future__ import annotations

import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlsplit, urlunsplit

from briareus_oidc import OidcTokenVerifier, TokenVerificationError
from briareus_websocket_transport.websocket_proxy import relay_websocket
from starlette.routing import WebSocketRoute
from starlette.websockets import WebSocket


def _websocket_backend_url(base_url: str, path: str) -> str:
    parsed = urlsplit(base_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunsplit((scheme, parsed.netloc, path, "", ""))


def _websocket_bearer(websocket: WebSocket) -> str:
    protocols = websocket.scope.get("subprotocols", [])
    if not isinstance(protocols, list) or "briareus.v1" not in protocols:
        return ""
    tokens = [
        value[7:] for value in protocols if isinstance(value, str) and value.startswith("bearer.")
    ]
    return tokens[0] if len(tokens) == 1 else ""


async def relay_panel_websocket(
    websocket: WebSocket,
    path: str,
    *,
    verifier: OidcTokenVerifier | None,
    public_base_url: str,
    backend_base_url: str,
) -> None:
    token = _websocket_bearer(websocket)
    if not token or verifier is None:
        await websocket.close(code=4401)
        return
    if websocket.headers.get("origin", "").rstrip("/") != public_base_url.rstrip("/"):
        await websocket.close(code=4403)
        return
    try:
        principal = await verifier.verify_async(token)
    except TokenVerificationError:
        await websocket.close(code=4401)
        return
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Forwarded-Host": websocket.headers.get("host", ""),
        "X-Forwarded-Proto": websocket.headers.get("x-forwarded-proto", "https"),
    }
    await relay_websocket(
        websocket,
        _websocket_backend_url(backend_base_url, path),
        headers=headers,
        origin=websocket.headers.get("origin"),
        subprotocol="briareus.v1",
        is_active=principal.is_active,
    )


def management_websocket_routes(
    relay: Callable[[WebSocket, str], Awaitable[None]],
) -> list[WebSocketRoute]:
    async def realtime(websocket: WebSocket) -> None:
        await relay(websocket, "/admin/api/realtime")

    async def operator(websocket: WebSocket) -> None:
        await relay(websocket, "/admin/api/browser/operator/ws")

    async def cdp(websocket: WebSocket) -> None:
        target_id = str(websocket.path_params.get("target_id") or "")
        if re.fullmatch(r"[A-Za-z0-9_-]{1,128}", target_id) is None:
            await websocket.close(code=4400)
            return
        await relay(websocket, f"/admin/api/browser/cdp/page/{target_id}")

    return [
        WebSocketRoute("/api/realtime", realtime),
        WebSocketRoute("/api/browser/operator/ws", operator),
        WebSocketRoute("/api/browser/cdp/page/{target_id}", cdp),
    ]
