from __future__ import annotations

import asyncio
import contextlib
from collections.abc import Callable, Mapping
from typing import Protocol

from briareus_zitadel_tokens import VerifiedPrincipal
from starlette.websockets import WebSocket, WebSocketDisconnect


class WebSocketRelay(Protocol):
    async def __call__(
        self,
        websocket: WebSocket,
        target_url: str,
        *,
        headers: Mapping[str, str] | None = None,
        origin: str | None = None,
        accept_downstream: bool = True,
        is_active: Callable[[], bool] | None = None,
    ) -> None: ...


async def token_socket_active(
    websocket: WebSocket,
    principal: VerifiedPrincipal,
) -> bool:
    if principal.is_active():
        return True
    with contextlib.suppress(RuntimeError):
        await websocket.close(code=4401)
    return False


async def watch_token_expiry(
    websocket: WebSocket,
    principal: VerifiedPrincipal,
    stopped: asyncio.Event,
) -> None:
    while not stopped.is_set():
        if not await token_socket_active(websocket, principal):
            return
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(stopped.wait(), timeout=1)


async def relay_authenticated_socket(
    websocket: WebSocket,
    target_url: str,
    *,
    principal: VerifiedPrincipal,
    headers: Mapping[str, str],
    relay: WebSocketRelay,
) -> None:
    def is_active() -> bool:
        return principal.is_active()

    protocols = websocket.scope.get("subprotocols", [])
    await websocket.accept(subprotocol="briareus.v1" if "briareus.v1" in protocols else None)
    relay_task = asyncio.create_task(
        relay(
            websocket,
            target_url,
            headers=headers,
            is_active=is_active,
            accept_downstream=False,
        )
    )
    stopped = asyncio.Event()
    watcher = asyncio.create_task(watch_token_expiry(websocket, principal, stopped))
    tasks = {relay_task, watcher}
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        for task in done:
            with contextlib.suppress(WebSocketDisconnect):
                task.result()
    finally:
        stopped.set()
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
